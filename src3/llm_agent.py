import asyncio
from playwright.async_api import async_playwright, Playwright
import sys
from enum import Enum
import ollama
from openai import OpenAI, AsyncOpenAI
from openai.types.shared import ResponsesModel
import os
from utils.file_utils import read_file
from client import AIClient, TOOLS, write_in_field, click_element
import json
from clean_dom import get_page_dom
import pyotp
import logging
from urllib.parse import urlparse

# Import AgentContext
from context import AgentContext

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# Standard security placeholders sent to the LLM (real credentials are swapped locally)
PLACEHOLDER_EMAIL = "USER_EMAIL"
PLACEHOLDER_PASSWORD = "USER_PASSWORD"


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


def is_valid_url(url: str) -> bool:
    if not url or url == "about:blank" or url.startswith("firefox-error://"):
        return False
    return True


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
    - Prioritize ID (`#id`) or Name (`[name='xyz']`) attributes for selectors as they are the most reliable.
    - Do not invent or hallucinate selectors. 
    - Issue the tool calls in the logical order (username -> password -> click).
    """.strip()


def handle_2fa_system_prompt() -> str:
    return """
    You are an expert browser automation agent. Your task is to complete a Two-Factor Authentication (2FA) page.

    You will be provided with the target website's HTML DOM and the REAL verification code.

    You have access to the following tools:
    - write_in_field(field: str, value: str): Types the `value` into the element identified by the `field` CSS selector.
    - click_element(selector: str): Clicks the element identified by the `selector` CSS selector.

    YOUR OBJECTIVE:
    1. Analyze the provided DOM to identify the OTP / verification code input field.
    2. Use the `write_in_field` tool to enter the provided verification code exactly as given.
    3. Identify the Verify / Continue / Submit button.
    4. Use the `click_element` tool to submit the form.

    CRITICAL RULES:
    - ONLY use CSS selectors that actually exist in the provided DOM.
    - Prioritize ID (`#id`) or Name (`[name='xyz']`) attributes whenever possible.
    - Do NOT invent or hallucinate selectors.
    - Issue the tool calls in the logical order (enter code -> click submit).
    """.strip()


def get_system_prompt(system_prompt: SystemPrompt) -> str:
    match system_prompt:
        case SystemPrompt.CHECK_LOGIN_SYSTEM_PROMPT:
            return check_login_system_prompt()
        case SystemPrompt.CHECK_2FA_SYSTEM_PROMPT:
            return check_2fa_system_prompt()
        case SystemPrompt.HADNLE_LOGIN_SYSTEM_PROMPT:
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


def handle_2fa_prompt(dom: str, totp_code: str) -> str:
    return f"""
    ---- START DOM ----
    {dom}
    ---- END DOM ----

    Analyze the DOM and identify the OTP/verification code field and the submit button.

    Use your tools to:
    1. Write the exact code `{totp_code}` into the verification code field.
    2. Click the submit button.

    IMPORTANT:
    - Write the exact code `{totp_code}` into the field.
    """.strip()


def get_prompt(prompt: Prompt, dom: str, totp_code: str = None) -> str:
    match prompt:
        case Prompt.CHECK_LOGIN_PROMPT:
            return check_login_prompt(dom)
        case Prompt.CHECK_2FA_PROMPT:
            return check_2fa_prompt(dom)
        case Prompt.HADNLE_LOGIN_PROMPT:
            return handle_login_prompt(dom)
        case Prompt.HANDLE_2FA_PROMPT:
            return handle_2fa_prompt(dom, totp_code)
        case _:
            raise RuntimeError(f"Invalid prompt: {prompt}")


def get_real_value(placeholder: str, ctx: AgentContext) -> str | None:
    """Maps placeholders to real credentials from AgentContext. Passes raw values (like TOTP) through."""
    match placeholder:
        case "USER_EMAIL" | "USERNAME":
            return ctx.email
        case "USER_PASSWORD" | "PASSWORD":
            return ctx.password
        case _:
            # If it's not a recognized placeholder, assume the LLM was given a direct value (e.g., TOTP code)
            return placeholder


async def execute_function_call(page, function: FunctionLLMTool, arguments, ctx: AgentContext):
    logger.info(f"Executing: {function.value}, with arguments: {arguments}")

    match function:
        case FunctionLLMTool.CLICK_ELEMENT:
            await click_element(page, arguments["selector"])
        case FunctionLLMTool.WRITE_IN_FIELD:
            real_value = get_real_value(arguments["value"], ctx)
            if real_value is None:
                placeholder = arguments["value"]
                logger.error("Calling write in field failed")
                logger.error(f"Error getting the real value from placeholder: {placeholder}")
                return
            
            # Mask logging if it looks like an email/password, but log normally otherwise
            log_val = "<redacted>" if arguments["value"] in [PLACEHOLDER_EMAIL, PLACEHOLDER_PASSWORD] else real_value
            logger.info("Writing in field (%s) with value %s", arguments["field"], log_val)
            
            await write_in_field(page, arguments["field"], real_value)
        case _:
            raise RuntimeError(f"Invalid function tool call for LLM: {function.value}")


async def is_login_page(page) -> bool:
    system_prompt = get_system_prompt(SystemPrompt.CHECK_LOGIN_SYSTEM_PROMPT)

    dom = await get_page_dom(page)

    prompt = get_prompt(Prompt.CHECK_LOGIN_PROMPT, dom)

    input_data = [{"role": "user", "content": f"{prompt}"}]
    ai_client = AIClient()
    response = ai_client.ask_client(input=input_data, instructions=system_prompt)

    return "yes" in response.output_text.strip().lower()


async def is_2fa_page(page) -> bool:
    system_prompt = get_system_prompt(SystemPrompt.CHECK_2FA_SYSTEM_PROMPT)

    dom = await get_page_dom(page)

    prompt = get_prompt(Prompt.CHECK_2FA_PROMPT, dom)

    input_data = [{"role": "user", "content": f"{prompt}"}]
    ai_client = AIClient()
    response = ai_client.ask_client(input=input_data, instructions=system_prompt)

    return "yes" in response.output_text.strip().lower()


async def handle_2fa(page, ctx: AgentContext):
    # Generate TOTP Code before talking to the LLM
    if not ctx.totp_secret:
        logger.error("No TOTP secret found in AgentContext")
        return
    
    try:
        totp = pyotp.TOTP(ctx.totp_secret)
        totp_code = totp.now()
        logger.info(f"Generated TOTP code directly: {totp_code}")
    except Exception as e:
        logger.error(f"Failed to generate TOTP code: {e}")
        return

    system_prompt = get_system_prompt(SystemPrompt.HANDLE_2FA_SYSTEM_PROMPT)
    dom = await get_page_dom(page)
    
    # Pass the real code to the prompt
    prompt = get_prompt(Prompt.HANDLE_2FA_PROMPT, dom, totp_code=totp_code)

    input_list = [{"role": "user", "content": f"{prompt}"}]

    logger.info("Creating AI client")
    try:
        ai_client = AIClient()
    except RuntimeError as e:
        logger.error(f"Error creating AIClient: {e}")
        return

    logger.info("Giving AI Client the tools")
    response = ai_client.ask_client(
        input=input_list, instructions=system_prompt, tools=TOOLS
    )

    available_functions = [f.value for f in FunctionLLMTool]
    logger.info(f"Available functions: {available_functions}")

    logger.info("Check which tools the agent needs, and call them")
    for item in response.output:
        if item.type == "function_call":
            if item.name in available_functions:
                arguments = json.loads(item.arguments)
                function = FunctionLLMTool(item.name)
                await execute_function_call(page, function, arguments, ctx)


async def handle_login(page, ctx: AgentContext):
    system_prompt = get_system_prompt(SystemPrompt.HADNLE_LOGIN_SYSTEM_PROMPT)

    dom = await get_page_dom(page)

    prompt = get_prompt(Prompt.HADNLE_LOGIN_PROMPT, dom)

    input_list = [{"role": "user", "content": f"{prompt}"}]

    logger.info("Creating AI client")
    try:
        ai_client = AIClient()
    except RuntimeError as e:
        logger.error(f"Error creating AIClient: {e}")
        return

    logger.info("Giving AI Client the tools")
    response = ai_client.ask_client(
        input=input_list, instructions=system_prompt, tools=TOOLS
    )

    available_functions = [f.value for f in FunctionLLMTool]
    logger.info(f"Available functions: {available_functions}")

    logger.info("Check which tools the agent needs, and call them")
    for item in response.output:
        if item.type == "function_call":
            if item.name in available_functions:
                arguments = json.loads(item.arguments)
                function = FunctionLLMTool(item.name)
                await execute_function_call(page, function, arguments, ctx)
