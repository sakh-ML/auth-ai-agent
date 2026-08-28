"""
Provides the AIAutomator class for fully AI-driven browser automation.

Responsible for interacting with the OpenAI API to perform DOM classification
(detecting login vs. 2FA pages) and executing form interactions via LLM
function tools (WRITE_IN_FIELD, CLICK_ELEMENT). Ensures security by intercepting
LLM tool calls to substitute placeholders with real credentials and dynamically
generated TOTP codes locally.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
import pyotp

from client import TOOLS, write_in_field, click_element
from context import AgentContext
from event import Event, log_event
from prompts import (
    get_system_prompt,
    get_prompt,
    Prompt,
    SystemPrompt,
    PLACEHOLDER_EMAIL,
    PLACEHOLDER_PASSWORD,
    PLACEHOLDER_TOTP,
)

logger = logging.getLogger(__name__)


class FunctionLLMTool(Enum):
    WRITE_IN_FIELD = "write_in_field"
    CLICK_ELEMENT = "click_element"


def get_totp(totp_secret) -> str | None:
    """
    Generates a time-based one-time password (TOTP) using the provided secret.
    Returns the TOTP string, or None if generation fails.
    """
    try:
        totp = pyotp.TOTP(totp_secret)
        totp_code = totp.now()
        logger.info(f"Generated TOTP code: {totp_code}")
        return totp_code
    except Exception as e:
        logger.error(f"Failed to generate TOTP code: {e}")
        return None


class AIAutomator:
    """
    Unified AI Automator class encapsulating DOM classification (is_login_page, is_2fa_page)
    and LLM tool execution for logins and 2FA authentication.
    """

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx

    def _get_real_value(self, placeholder: str, url: str) -> str | None:
        """Maps placeholders to real credentials from Vault or AgentContext."""
        cred = self.ctx.vault.get_credential(url)

        match placeholder:
            case "USER_EMAIL" | "USERNAME":
                if cred and cred.username:
                    return cred.username

            case "USER_PASSWORD" | "PASSWORD":
                if cred and cred.password:
                    return cred.password

            case "USER_TOTP" | "TOTP":
                totp_secret = None
                if cred and cred.totp_secret:
                    totp_secret = cred.totp_secret

                if not totp_secret:
                    logger.error("No TOTP secret available to resolve placeholder")
                    return None

                totp_code = get_totp(totp_secret)
                if totp_code is None:
                    logger.error("Failed to get TOTP")
                    return None
                return totp_code

            case _:
                return None
        return None

    async def _execute_function_call(
        self, page, function: FunctionLLMTool, arguments: dict, human_like: bool = False
    ) -> bool:
        """Executes LLM tool instructions and substitutes placeholders locally.

        Returns False when a value could not be resolved (e.g. a code/token
        field we have no stored value for), so callers can avoid submitting
        a form they know is incomplete.
        """
        logger.debug(f"Executing: {function.value}, with arguments: {arguments}")

        match function:
            case FunctionLLMTool.CLICK_ELEMENT:
                await click_element(page, arguments["selector"])
                return True

            case FunctionLLMTool.WRITE_IN_FIELD:
                field = arguments["field"]
                raw_val = arguments["value"]
                real_value = self._get_real_value(raw_val, page.url)

                if real_value is None:
                    logger.error("Calling write in field failed")
                    logger.error(
                        f"Error getting the real value from placeholder: {raw_val}"
                    )
                    return False

                # Redact logs if value is a credential
                sensitive_placeholders = [
                    PLACEHOLDER_EMAIL,
                    PLACEHOLDER_PASSWORD,
                    PLACEHOLDER_TOTP,
                ]
                log_val = (
                    "<redacted>" if raw_val in sensitive_placeholders else real_value
                )
                logger.info("Writing in field (%s) with value %s", field, log_val)

                if human_like:
                    await page.click(field)
                    await page.type(field, real_value, delay=110)
                else:
                    await write_in_field(page, field, real_value)
                return True

            case _:
                raise RuntimeError(
                    f"Invalid function tool call for LLM: {function.value}"
                )

    async def _run_tool_calls(self, page, response, human_like: bool) -> bool:
        """
        Executes tool calls sequentially in the order returned by the LLM.
        Aborts immediately if any field fails to resolve to a real value,
        preventing incomplete form submissions.
        """
        available_functions = [f.value for f in FunctionLLMTool]

        for item in response.output:
            if item.type != "function_call" or item.name not in available_functions:
                continue

            arguments = json.loads(item.arguments)
            function = FunctionLLMTool(item.name)

            success = await self._execute_function_call(
                page, function, arguments, human_like
            )
            if not success:
                logger.warning(
                    "Not every field could be resolved to a real value; "
                    "skipping submit to avoid sending an incomplete form."
                )
                return False

        return True

    # ------------------------------------------
    # DETECTION METHODS
    # ------------------------------------------

    async def is_login_page(self, page) -> bool:
        """Checks if the current page is a login form using LLM classification."""
        try:
            system_prompt = get_system_prompt(SystemPrompt.CHECK_LOGIN_SYSTEM_PROMPT)
            # dom = await get_page_dom(page)
            dom = await page.content()
            prompt = get_prompt(Prompt.CHECK_LOGIN_PROMPT, dom)

            input_data = [{"role": "user", "content": f"{prompt}"}]

            log_event(Event.ASKING_LLM_STARTED)
            response = await self.ctx.ai_client.ask_client(
                user_input=input_data, instructions=system_prompt
            )
            log_event(Event.ASKING_LLM_FINISHED)

            response = response.output_text.strip().lower()
            return response == "yes"
        except Exception as e:
            logger.error(f"is_login_page check failed: {e}")
            return False

    async def is_2fa_page(self, page) -> bool:
        """Checks if the current page is a 2FA/OTP form using LLM classification."""
        try:
            system_prompt = get_system_prompt(SystemPrompt.CHECK_2FA_SYSTEM_PROMPT)
            dom = await page.content()
            prompt = get_prompt(Prompt.CHECK_2FA_PROMPT, dom)

            input_data = [{"role": "user", "content": f"{prompt}"}]

            log_event(Event.ASKING_LLM_STARTED)
            response = await self.ctx.ai_client.ask_client(
                user_input=input_data, instructions=system_prompt
            )
            log_event(Event.ASKING_LLM_FINISHED)

            response = response.output_text.strip().lower()
            return response == "yes"
        except Exception as e:
            logger.error(f"is_2fa_page check failed: {e}")
            return False

    # ------------------------------------------
    # ACTION METHODS
    # ------------------------------------------

    async def login(self, page, human_like: bool = False) -> bool:
        """Performs automated login via LLM function calls and local credential swapping.

        Returns False (without submitting) if a field on the page - e.g. an
        additional one-time token field - could not be resolved to a real
        value. The caller should fall back to observing the page so a human
        completing it manually can still be learned from.
        """
        url = page.url
        logger.info(f"AIAutomator: Handling login for {url}")

        try:
            system_prompt = get_system_prompt(SystemPrompt.HANDLE_LOGIN_SYSTEM_PROMPT)
            dom = await page.content()
            prompt = get_prompt(Prompt.HANDLE_LOGIN_PROMPT, dom)

            input_list = [{"role": "user", "content": f"{prompt}"}]

            log_event(Event.ASKING_LLM_STARTED)
            response = await self.ctx.ai_client.ask_client(
                user_input=input_list, instructions=system_prompt, tools=TOOLS
            )
            log_event(Event.ASKING_LLM_FINISHED)

            return await self._run_tool_calls(page, response, human_like)

        except Exception as e:
            logger.error(f"LLM login failed for {url}: {e}")
            return False

    async def submit_2fa(self, page, human_like: bool = False) -> bool:
        """
        Completes 2FA verification via LLM tool calls.

        Mirrors `login()`: the LLM only ever sees the PLACEHOLDER_TOTP token and
        picks the right field/button for it. The real, freshly-generated TOTP
        code is substituted locally in `_execute_function_call` -> `_get_real_value`,
        so the live code itself is never sent to the LLM.
        """
        url = page.url
        logger.info(f"AIAutomator: Handling 2FA for {url}")

        totp_secret = None
        cred = self.ctx.vault.get_credential(url)
        if cred and cred.totp_secret:
            totp_secret = cred.totp_secret

        if not totp_secret:
            logger.error(f"No TOTP secret found in AgentContext or Vault for {url}")
            return False

        try:
            system_prompt = get_system_prompt(SystemPrompt.HANDLE_2FA_SYSTEM_PROMPT)
            dom = await page.content()
            prompt = get_prompt(Prompt.HANDLE_2FA_PROMPT, dom)

            input_list = [{"role": "user", "content": f"{prompt}"}]

            log_event(Event.ASKING_LLM_STARTED)
            response = await self.ctx.ai_client.ask_client(
                user_input=input_list, instructions=system_prompt, tools=TOOLS
            )
            log_event(Event.ASKING_LLM_FINISHED)

            return await self._run_tool_calls(page, response, human_like)

        except Exception as e:
            logger.error(f"LLM 2FA submission failed for {url}: {e}")
            return False
