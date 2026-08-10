"""
src/automator.py

Fully AI-driven browser automator. Performs DOM classification (login vs 2FA)
and handles form interactions using LLM function tools, dynamic TOTP generation,
and secure local credential replacement.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Optional
import pyotp

from client import TOOLS, write_in_field, click_element
from clean_dom import get_page_dom
from context import AgentContext

logger = logging.getLogger(__name__)

# Standard security placeholders sent to the LLM (real credentials are swapped locally)
PLACEHOLDER_EMAIL = "USER_EMAIL"
PLACEHOLDER_PASSWORD = "USER_PASSWORD"
PLACEHOLDER_TOTP = "USER_TOTP"


class FunctionLLMTool(Enum):
    WRITE_IN_FIELD = "write_in_field"
    CLICK_ELEMENT = "click_element"


class SystemPrompt(Enum):
    CHECK_LOGIN_SYSTEM_PROMPT = 0
    CHECK_2FA_SYSTEM_PROMPT = 1
    HANDLE_LOGIN_SYSTEM_PROMPT = 2
    HANDLE_2FA_SYSTEM_PROMPT = 3


class Prompt(Enum):
    CHECK_LOGIN_PROMPT = 0
    CHECK_2FA_PROMPT = 1
    HANDLE_LOGIN_PROMPT = 2
    HANDLE_2FA_PROMPT = 3


def is_valid_url(url: str) -> bool:
    if not url or url == "about:blank" or url.startswith("firefox-error://"):
        return False
    return True


def get_totp(totp_secret) -> Optional[str]:
    try:
        totp = pyotp.TOTP(totp_secret)
        totp_code = totp.now()
        logger.info(f"Generated TOTP code: {totp_code}")
        return totp_code
    except Exception as e:
        logger.error(f"Failed to generate TOTP code: {e}")
        return None


# ==========================================
# SYSTEM PROMPTS & PROMPT GENERATORS
# ==========================================


def check_login_system_prompt() -> str:
    return """
    You are a strict binary classifier for HTML DOM content.

    TASK: Decide if the given DOM is a LOGIN page (username/email + password form to authenticate an existing user).

    POSITIVE indicators: input type="password", fields like "username"/"email"/"user id", submit buttons like "Log in"/"Sign in".
    NEGATIVE (answer "no"): registration/sign-up pages, password-reset pages, 2FA/OTP/verification-code pages, unrelated pages.

    OUTPUT FORMAT (mandatory):
    - Output exactly one token: yes or no
    - Lowercase only
    - No punctuation, no quotes, no spaces, no newline, no explanation, no reasoning
    - Any output other than "yes" or "no" is invalid
    """.strip()


def check_2fa_system_prompt() -> str:
    return """
    You are a strict binary classifier for HTML DOM content.

    TASK: Decide if the given DOM is a 2FA / OTP / VERIFICATION page (asks the user to enter a one-time code sent via SMS, email, or authenticator app).

    POSITIVE indicators: fields like "code"/"OTP"/"verification code"/"authentication code", short numeric-only inputs (4-8 digits), text like "enter the code sent to your phone/email".
    NEGATIVE (answer "no"): plain username/password login pages, registration pages, unrelated pages.

    OUTPUT FORMAT (mandatory):
    - Output exactly one token: yes or no
    - Lowercase only
    - No punctuation, no quotes, no spaces, no newline, no explanation, no reasoning
    - Any output other than "yes" or "no" is invalid
    """.strip()


def handle_login_system_prompt() -> str:
    return """
    You are an expert browser automation agent. Your task is to log a user into a website.
    You will be provided with the target website's HTML DOM and PLACEHOLDER values for credentials.

    You have access to the following tools:
    - write_in_field(field: str, value: str): Types the `value` into the element identified by the `field` CSS selector.
    - click_element(selector: str): Clicks the element identified by the `selector` CSS selector.

    YOUR OBJECTIVE:
    1. Analyze the provided DOM to identify the exact CSS selectors for the username/email input, the password input, and the submit button.
    2. Use the `write_in_field` tool to enter the provided username placeholder.
    3. Use the `write_in_field` tool to enter the provided password placeholder.
    4. Use the `click_element` tool to click the login/submit button.

    CRITICAL RULES:
    - ONLY use CSS selectors that actually exist in the provided DOM (e.g., `#username`, `input[name='login']`, `.submit-btn`).
    - Prioritize ID (`#id`) or Name (`[name='xyz']`) attributes as they are the most reliable.
    - Do not invent or hallucinate selectors.
    - Issue the tool calls in the logical order (username -> password -> click).
    """.strip()


def handle_2fa_system_prompt() -> str:
    return """
    You are an expert browser automation agent. Your task is to complete a Two-Factor Authentication (2FA) page.
    You will be provided with the target website's HTML DOM and a PLACEHOLDER value for the verification code.

    You have access to the following tools:
    - write_in_field(field: str, value: str): Types the `value` into the element identified by the `field` CSS selector.
    - click_element(selector: str): Clicks the element identified by the `selector` CSS selector.

    YOUR OBJECTIVE:
    1. Analyze the provided DOM to identify the exact CSS selector for the OTP / verification code input field.
    2. Use the `write_in_field` tool to enter the provided verification code placeholder.
    3. Identify the Verify / Continue / Submit button.
    4. Use the `click_element` tool to submit the form.

    CRITICAL RULES:
    - ONLY use CSS selectors that actually exist in the provided DOM.
    - Prioritize ID (`#id`) or Name (`[name='xyz']`) attributes whenever possible.
    - Do not invent or hallucinate selectors.
    - ALWAYS use the placeholder value exactly as given for the verification code field.
    - NEVER invent a different placeholder or a real-looking code.
    - The placeholder will be replaced with the real verification code by the runtime after your tool call.
    - Issue the tool calls in the logical order (enter code -> click submit).
    """.strip()


def get_system_prompt(system_prompt: SystemPrompt) -> str:
    match system_prompt:
        case SystemPrompt.CHECK_LOGIN_SYSTEM_PROMPT:
            return check_login_system_prompt()
        case SystemPrompt.CHECK_2FA_SYSTEM_PROMPT:
            return check_2fa_system_prompt()
        case SystemPrompt.HANDLE_LOGIN_SYSTEM_PROMPT:
            return handle_login_system_prompt()
        case SystemPrompt.HANDLE_2FA_SYSTEM_PROMPT:
            return handle_2fa_system_prompt()
        case _:
            raise RuntimeError(f"Invalid system_prompt: {system_prompt}")


def check_login_prompt(dom: str) -> str:
    return f"""
    ---- START DOM ----
    {dom}
    ---- END DOM ----

    Classify the DOM above per your instructions.
    Output only: yes or no
    """.strip()


def check_2fa_prompt(dom: str) -> str:
    return f"""
    ---- START DOM ----
    {dom}
    ---- END DOM ----

    Classify the DOM above per your instructions.
    Output only: yes or no
    """.strip()


def handle_login_prompt(dom: str) -> str:
    return f"""
    ---- START DOM ----
    {dom}
    ---- END DOM ----

    Analyze the DOM and identify the username/email field, the password field, and the login button.

    Use your tools to:
    1. Write the placeholder `{PLACEHOLDER_EMAIL}` into the username/email field.
    2. Write the placeholder `{PLACEHOLDER_PASSWORD}` into the password field.
    3. Click the login button.

    IMPORTANT:
    - ALWAYS use the placeholder `{PLACEHOLDER_EMAIL}` for the username/email field.
    - ALWAYS use the placeholder `{PLACEHOLDER_PASSWORD}` for the password field.
    - NEVER use any real credentials.
    - NEVER invent different placeholder names.
    - The placeholders will be replaced with the real credentials by the runtime after your tool call.
    """.strip()


def handle_2fa_prompt(dom: str) -> str:
    return f"""
    ---- START DOM ----
    {dom}
    ---- END DOM ----

    Analyze the DOM and identify the OTP/verification code field and the submit button.

    Use your tools to:
    1. Write the placeholder `{PLACEHOLDER_TOTP}` into the verification code field.
    2. Click the submit button.

    IMPORTANT:
    - ALWAYS use the placeholder `{PLACEHOLDER_TOTP}` for the verification code field.
    - NEVER use a real or invented code.
    - NEVER invent a different placeholder name.
    - The placeholder will be replaced with the real verification code by the runtime after your tool call.
    """.strip()


def get_prompt(prompt: Prompt, dom: str) -> str:
    match prompt:
        case Prompt.CHECK_LOGIN_PROMPT:
            return check_login_prompt(dom)
        case Prompt.CHECK_2FA_PROMPT:
            return check_2fa_prompt(dom)
        case Prompt.HANDLE_LOGIN_PROMPT:
            return handle_login_prompt(dom)
        case Prompt.HANDLE_2FA_PROMPT:
            return handle_2fa_prompt(dom)
        case _:
            raise RuntimeError(f"Invalid prompt: {prompt}")


# ==========================================
# AI AUTOMATOR CLASS
# ==========================================


class AIAutomator:
    """
    Unified AI Automator class encapsulating DOM classification (is_login_page, is_2fa_page)
    and LLM tool execution for logins and 2FA authentication.
    """

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx

    def _get_real_value(self, placeholder: str, url: str) -> Optional[str]:
        """Maps placeholders to real credentials from Vault or AgentContext."""
        cred = self.ctx.vault.get_credential(url)

        match placeholder:
            case "USER_EMAIL" | "USERNAME":
                if cred and cred.username:
                    return cred.username
                return getattr(self.ctx, "email", None)

            case "USER_PASSWORD" | "PASSWORD":
                if cred and cred.password:
                    return cred.password
                return getattr(self.ctx, "password", None)

            case "USER_TOTP" | "TOTP":
                totp_secret = None
                if cred and cred.totp_secret:
                    totp_secret = cred.totp_secret
                elif hasattr(self.ctx, "totp_secret"):
                    totp_secret = self.ctx.totp_secret

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

    async def _execute_function_call(
        self, page, function: FunctionLLMTool, arguments: dict, human_like: bool = False
    ) -> None:
        """Executes LLM tool instructions and substitutes placeholders locally."""
        logger.info(f"Executing: {function.value}, with arguments: {arguments}")

        match function:
            case FunctionLLMTool.CLICK_ELEMENT:
                await click_element(page, arguments["selector"])

            case FunctionLLMTool.WRITE_IN_FIELD:
                field = arguments["field"]
                raw_val = arguments["value"]
                real_value = self._get_real_value(raw_val, page.url)

                if real_value is None:
                    logger.error("Calling write in field failed")
                    logger.error(
                        f"Error getting the real value from placeholder: {raw_val}"
                    )
                    return

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

            case _:
                raise RuntimeError(
                    f"Invalid function tool call for LLM: {function.value}"
                )

    # ------------------------------------------
    # DETECTION METHODS
    # ------------------------------------------

    async def is_login_page(self, page) -> bool:
        """Checks if the current page is a login form using LLM classification."""
        try:
            system_prompt = get_system_prompt(SystemPrompt.CHECK_LOGIN_SYSTEM_PROMPT)
            #dom = await get_page_dom(page)
            dom = await page.content()
            prompt = get_prompt(Prompt.CHECK_LOGIN_PROMPT, dom)

            input_data = [{"role": "user", "content": f"{prompt}"}]
            response = self.ctx.ai_client.ask_client(
                input=input_data, instructions=system_prompt
            )

            return "yes" in response.output_text.strip().lower()
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
            response = self.ctx.ai_client.ask_client(
                input=input_data, instructions=system_prompt
            )

            return "yes" in response.output_text.strip().lower()
        except Exception as e:
            logger.error(f"is_2fa_page check failed: {e}")
            return False

    # ------------------------------------------
    # ACTION METHODS
    # ------------------------------------------

    async def login(self, page, human_like: bool = False) -> bool:
        """Performs automated login via LLM function calls and local credential swapping."""
        url = page.url
        logger.info(f"AIAutomator: Handling login for {url}")

        try:
            system_prompt = get_system_prompt(SystemPrompt.HANDLE_LOGIN_SYSTEM_PROMPT)
            dom = await page.content()
            prompt = get_prompt(Prompt.HANDLE_LOGIN_PROMPT, dom)

            input_list = [{"role": "user", "content": f"{prompt}"}]

            response = self.ctx.ai_client.ask_client(
                input=input_list, instructions=system_prompt, tools=TOOLS
            )

            available_functions = [f.value for f in FunctionLLMTool]

            for item in response.output:
                if item.type == "function_call" and item.name in available_functions:
                    arguments = json.loads(item.arguments)
                    function = FunctionLLMTool(item.name)
                    await self._execute_function_call(
                        page, function, arguments, human_like
                    )

            return True

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

        # Fail fast if no TOTP secret is available at all (Vault or AgentContext),
        # before spending an LLM call on a page we can't actually complete.
        totp_secret = None
        if hasattr(self.ctx, "vault"):
            cred = self.ctx.vault.get_credential(url)
            if cred and cred.totp_secret:
                totp_secret = cred.totp_secret

        if not totp_secret and hasattr(self.ctx, "totp_secret"):
            totp_secret = self.ctx.totp_secret

        if not totp_secret:
            logger.error(f"No TOTP secret found in AgentContext or Vault for {url}")
            return False

        try:
            system_prompt = get_system_prompt(SystemPrompt.HANDLE_2FA_SYSTEM_PROMPT)
            dom = await page.content()
            prompt = get_prompt(Prompt.HANDLE_2FA_PROMPT, dom)

            input_list = [{"role": "user", "content": f"{prompt}"}]

            response = self.ctx.ai_client.ask_client(
                input=input_list, instructions=system_prompt, tools=TOOLS
            )

            available_functions = [f.value for f in FunctionLLMTool]

            for item in response.output:
                if item.type == "function_call" and item.name in available_functions:
                    arguments = json.loads(item.arguments)
                    function = FunctionLLMTool(item.name)
                    await self._execute_function_call(
                        page, function, arguments, human_like
                    )

            return True

        except Exception as e:
            logger.error(f"LLM 2FA submission failed for {url}: {e}")
            return False
