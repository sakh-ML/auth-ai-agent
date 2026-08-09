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
import logging

logger = logging.getLogger(__name__)


class FunctionLLMTool(Enum):
    WRITE_IN_FIELD = "write_in_field"
    CLICK_ELEMENT = "click_element"


class SystemPrompt(Enum):
    CHECK_LOGIN_SYSTEM_PROMPT = 0
    CHECK_2FA_SYSTEM_PROMPT = 1
    HANDLE_ACTION_SYSTEM_PROMPT = 4


class Prompt(Enum):
    CHECK_LOGIN_PROMPT = 0
    CHECK_2FA_PROMPT = 1
    HANDLE_ACTION_PROMPT = 4


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


def handle_action_system_prompt() -> str:
    return """
    You are a universal browser authentication agent. You are shown ONE page at a
    time as a cleaned DOM snippet. You do not know which website you are on, and
    you must never assume a specific site's layout, selectors, or flow. You decide
    everything purely from what is present in the given DOM.

    You have exactly two tools:
    - write_in_field(field: str, value: str): types `value` into the input element
      matched by the CSS selector `field`.
    - click_element(selector: str): clicks the element matched by the CSS selector
      `selector`.

    You will be given the user's credentials (username, password, and — if
    available — a one-time verification code). The page shown to you will match
    exactly one of these states. Identify which one, then act accordingly:

    1. COMBINED LOGIN (username/email field + password field + submit button all
       present on this page):
       - Fill the username/email field with the provided username.
       - Fill the password field with the provided password.
       - Click the submit/login button.
       - Issue all tool calls in this order, in a single turn.

    2. FIRST STEP OF A MULTI-STEP LOGIN (only a username/email field is present,
       with a "Next"/"Continue" button, no password field on this page):
       - Fill the username/email field with the provided username.
       - Click the continue/next button.
       - Do NOT reference a password field — it does not exist on this page.

    3. SECOND STEP OF A MULTI-STEP LOGIN (a password field is present, but no
       username/email field on this page):
       - Fill the password field with the provided password.
       - Click the login/submit button.

    4. 2FA / OTP / VERIFICATION STEP (a short code field described as "code",
       "OTP", "verification code", "authentication code", etc.):
       - If a verification code was provided to you, fill the code field with it
         and click the verify/submit/confirm button.
       - If no verification code was provided (empty or marked not available),
         do NOT invent, guess, or fabricate a code. Take no tool call at all in
         this case.

    5. ANY OTHER PAGE (error page, already-logged-in page, unrelated content,
       CAPTCHA, or a page where no relevant field can be confidently identified):
       - Take no action. Do not call any tool.

    STRICT RULES:
    - Only use selectors (id, name, or class) that are literally present in the
      DOM you were given. Never invent, guess, or hallucinate a selector.
    - Prefer `#id` or `[name="..."]` selectors over class-based ones — they are
      more stable.
    - If a field is ambiguous (e.g. two visible password inputs), prefer the one
      inside a `<form>`; if still ambiguous, take no action.
    - Never click more than one submit-type button per turn.
    - Never repeat an action the DOM shows is already done (field already filled,
      page already shows a logged-in/success state).
    - Respond ONLY with tool calls (or no tool call, per rules 4/5) — no
      explanations, no reasoning text.
    """.strip()


def get_system_prompt(system_prompt: SystemPrompt) -> str:
    match system_prompt:
        case SystemPrompt.CHECK_LOGIN_SYSTEM_PROMPT:
            return check_login_system_prompt()
        case SystemPrompt.CHECK_2FA_SYSTEM_PROMPT:
            return check_2fa_system_prompt()
        case SystemPrompt.HANDLE_ACTION_SYSTEM_PROMPT:
            return handle_action_system_prompt()
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


def handle_action_prompt(dom: str) -> str:
    credits = read_file("password2.txt")

    return f"""
    Here are the credentials for this session:
    {credits}

    ---- START DOM ----
    {dom}
    ---- END DOM ----

    Analyze the DOM above, determine which state it represents per your
    instructions, and issue the correct tool call(s).
    """.strip()


def get_prompt(prompt: Prompt, dom: str) -> str:
    match prompt:
        case Prompt.CHECK_LOGIN_PROMPT:
            return check_login_prompt(dom)
        case Prompt.CHECK_2FA_PROMPT:
            return check_2fa_prompt(dom)
        case Prompt.HANDLE_ACTION_PROMPT:
            return handle_action_prompt(dom)
        case _:
            raise RuntimeError(f"Invalid prompt: {prompt}")


async def execute_function_call(page, function: FunctionLLMTool, arguments):
    print(f"Trying to execute: {function.value}")
    match function:
        case FunctionLLMTool.CLICK_ELEMENT:
            await click_element(page, arguments["selector"])
        case FunctionLLMTool.WRITE_IN_FIELD:
            await write_in_field(page, arguments["field"], arguments["value"])
        case _:
            raise RuntimeError(f"Invalid function tool call for LLM: {function.value}")


async def is_login_page(page) -> bool:
    system_prompt = get_system_prompt(SystemPrompt.CHECK_LOGIN_SYSTEM_PROMPT)

    # this is clean dom
    dom = await get_page_dom(page)

    prompt = get_prompt(Prompt.CHECK_LOGIN_PROMPT, dom)

    input = [{"role": "user", "content": f"{prompt}"}]
    ai_client = AIClient()
    response = ai_client.ask_client(input=input, instructions=system_prompt)

    return "yes" in response.output_text.strip().lower()


async def is_2fa_page(page) -> bool:
    system_prompt = get_system_prompt(SystemPrompt.CHECK_2FA_SYSTEM_PROMPT)

    dom = await get_page_dom(page)

    prompt = get_prompt(Prompt.CHECK_2FA_PROMPT, dom)

    input = [{"role": "user", "content": f"{prompt}"}]
    ai_client = AIClient()
    response = ai_client.ask_client(input=input, instructions=system_prompt)

    return "yes" in response.output_text.strip().lower()


async def handle_action(page, max_steps: int = 6):
    system_prompt = get_system_prompt(SystemPrompt.HANDLE_ACTION_SYSTEM_PROMPT)
    ai_client = AIClient()
    available_functions = [f.value for f in FunctionLLMTool]

    for step in range(max_steps):
        dom = await get_page_dom(page)
        prompt = handle_action_prompt(dom)
        input_list = [{"role": "user", "content": prompt}]

        response = ai_client.ask_client(
            input=input_list, instructions=system_prompt, tools=TOOLS
        )

        function_calls = [
            item for item in response.output if item.type == "function_call"
        ]
        logger.info(
            f"Step {step}: model returned {len(function_calls)} function call(s)"
        )

        if not function_calls:
            logger.info("Model returned no action — assuming step complete.")
            break

        for item in function_calls:
            if item.name in available_functions:
                arguments = json.loads(item.arguments)
                function = FunctionLLMTool(item.name)
                await execute_function_call(page, function, arguments)

        # small pause in case the action triggers a re-render / navigation
        await page.wait_for_timeout(500)


# Called automatically from playwright when a url get loaded
# hier look if thsi is a 2fa or login page
# if yes we have to do the thing itself :)
async def on_page_load_openai(page):
    # Hier call the LLM to check if this is a login website when yes perform the thing :O
    current_url = page.url

    if not is_valid_url(current_url):
        return

    print("-" * 50 + "\n")

    logger.info("Handling required action ....")

    # print("Asking Client if this is an login or a 2fa page")

    # if not await is_login_page(page) and not await is_2fa_page(page):
    #    print("its not a login or 2fa page.")
    #    return

    await handle_action(page)
    # await handle_login(page)

    # if not await is_2fa_page():
    #    return

    # handle 2fa


async def run(playwright: Playwright, url: str):
    firefox = playwright.firefox  # or "chrome" or etc ..
    browser = await firefox.launch(headless=False)
    page = await browser.new_page()
    # page.on("load", on_page_load)
    # callback function when the url of the website changes
    logger.info("Setting a callback function when a page load: on_page_load_openai")
    page.on("load", on_page_load_openai)
    await page.goto(url)

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting script...")
    finally:
        await browser.close()


async def main():
    url = "https://practicetestautomation.com/practice-test-login/"

    async with async_playwright() as playwright:
        await run(playwright, url)


if __name__ == "__main__":
    asyncio.run(main())
