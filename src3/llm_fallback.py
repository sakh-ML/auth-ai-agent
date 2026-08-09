"""
src/llm_fallback.py

LLM fallback for portal logins whose deterministic selectors
(portals.LOGIN_SELECTORS / TOTP_SELECTORS) are missing or fail on the
live page. Reuses your existing src/client.py (AIClient, TOOLS,
write_in_field, click_element) and src/clean_dom.py.

SECURITY - credential placeholder pattern:
The real password / TOTP code are NEVER included in the prompt sent to
the LLM. Placeholders are sent instead, and only swapped for the real
values locally, right before the browser executes the fill action -
same principle as your colleague's SAIA-based script
(substitute_credentials / CREDENTIAL_MAP). The TOTP secret itself is
never sent anywhere; only the already-computed 6-digit code placeholder
is used, and even that placeholder is substituted before any DOM write.
"""

from __future__ import annotations
import json
import logging
from enum import Enum

from client import AIClient, TOOLS, write_in_field, click_element
from clean_dom import get_page_dom
from context import AgentContext


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

class FunctionLLMTool(Enum):
    WRITE_IN_FIELD = "write_in_field"
    CLICK_ELEMENT = "click_element"


class SystemPrompt(Enum):
    CHECK_LOGIN_SYSTEM_PROMPT = 0
    CHECK_2FA_SYSTEM_PROMPT = 1
    HADNLE_LOGIN_SYSTEM_PROMPT = 2
    HANDLE_2FA_SYSTEM_PROMPT = 3


class Prompt(Enum):
    CHECK_LOGIN_PROMPT = 0
    CHECK_2FA_PROMPT = 1
    HADNLE_LOGIN_PROMPT = 2
    HANDLE_2FA_PROMPT = 3


class AnswerFromLLM(Enum):
    YES = 0
    NO = 1
    UNKOWN = 2
    

PLACEHOLDER_EMAIL = "USER_EMAIL"
PLACEHOLDER_PASSWORD = "USER_PASSWORD"
PLACEHOLDER_TOTP = "USER_TOTP_CODE"


def _login_fallback_system_prompt() -> str:
    return """
    You are an expert browser automation agent. Your task is to log a user into a website.
    You will be provided with the target website's HTML DOM and PLACEHOLDER values
    for the username and password - never real credentials.

    You have access to the following tools:
    - write_in_field(field: str, value: str): types `value` into the element identified by the `field` CSS selector.
    - click_element(selector: str): clicks the element identified by `selector`.

    OBJECTIVE:
    1. Identify the CSS selectors for the username/email field, the password field, and the submit button.
    2. Call write_in_field with the given placeholder for username, then for password.
    3. Call click_element for the submit button LAST, only after both fields are filled.

    RULES:
    - Only use selectors that actually appear in the DOM (prefer id/name attributes).
    - Do not invent or hallucinate selectors.
    - Never reorder: fill fields first, click last.
    """.strip()


def _totp_fallback_system_prompt() -> str:
    return """
    You are an expert browser automation agent. Your task is to submit a
    one-time TOTP code on a 2FA verification page.
    You will be given a PLACEHOLDER for the 6-digit code - never the real code.

    You have access to the following tools:
    - write_in_field(field: str, value: str)
    - click_element(selector: str)

    OBJECTIVE:
    1. Identify the CSS selector of the code input field and the submit button.
    2. Call write_in_field with the placeholder value for the code field.
    3. Call click_element for the submit button, LAST.

    RULES:
    - Only use selectors that actually appear in the DOM.
    - Do not invent selectors.
    """.strip()


def _substitute(value: str, real_map: dict[str, str]) -> str:
    for placeholder, real in real_map.items():
        value = value.replace(placeholder, real)
    return value


async def _run_tool_calls(page, response, real_map: dict[str, str]) -> None:
    """Executes the LLM's tool calls, substituting placeholders with real
    values right here - the last possible moment before browser execution."""
    available = {"write_in_field", "click_element"}
    fills, clicks = [], []

    for item in response.output:
        if item.type == "function_call" and item.name in available:
            args = json.loads(item.arguments)
            (fills if item.name == "write_in_field" else clicks).append((item.name, args))

    # Safety net: always fill before clicking, regardless of the order
    # the LLM actually returned the tool calls in.
    for name, args in fills + clicks:
        if name == "write_in_field":
            real_value = _substitute(args["value"], real_map)
            logger.info("LLM fallback: write_in_field(%s, <redacted>)", args["field"])
            await write_in_field(page, args["field"], real_value)
        elif name == "click_element":
            logger.info("LLM fallback: click_element(%s)", args["selector"])
            await click_element(page, args["selector"])


async def llm_login_fallback(page, ctx: AgentContext) -> None:
    """Called when deterministic selectors failed for a portal's username
    /password form. Real email/password are substituted locally, after
    the LLM has already responded with tool calls."""
    dom = await get_page_dom(page)
    system_prompt = _login_fallback_system_prompt()
    prompt = f"""
    Fill the username/email field with "{PLACEHOLDER_EMAIL}" and the
    password field with "{PLACEHOLDER_PASSWORD}", then click submit.

    ---- START DOM ----
    {dom}
    ---- END DOM ----
    """.strip()

    ai_client = AIClient()
    response = ai_client.ask_client(
        input=[{"role": "user", "content": prompt}],
        instructions=system_prompt,
        tools=TOOLS,
    )

    real_map = {PLACEHOLDER_EMAIL: ctx.email, PLACEHOLDER_PASSWORD: ctx.password}
    await _run_tool_calls(page, response, real_map)


async def llm_totp_fallback(page, ctx: AgentContext) -> None:
    """Called when deterministic TOTP selectors failed (or aren't
    configured) for a portal's 2FA step. The 6-digit code is generated
    locally from the learned secret; only its placeholder is sent to the
    LLM, and the raw secret itself is never transmitted anywhere."""
    import pyotp

    if not ctx.totp_secret:
        logger.warning("No TOTP secret known, cannot run TOTP fallback")
        return

    code = pyotp.TOTP(ctx.totp_secret).now()

    dom = await get_page_dom(page)
    system_prompt = _totp_fallback_system_prompt()
    prompt = f"""
    Fill the 6-digit code field with "{PLACEHOLDER_TOTP}", then click submit.

    ---- START DOM ----
    {dom}
    ---- END DOM ----
    """.strip()

    ai_client = AIClient()
    response = ai_client.ask_client(
        input=[{"role": "user", "content": prompt}],
        instructions=system_prompt,
        tools=TOOLS,
    )

    real_map = {PLACEHOLDER_TOTP: code}
    await _run_tool_calls(page, response, real_map)