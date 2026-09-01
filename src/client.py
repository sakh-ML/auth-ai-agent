"""
Configures the AIClient for interacting with the OpenAI-compatible API.

Defines the executable browser interaction tools (write_in_field, click_element)
provided to the LLM, and handles the formatting, parameterization, and
execution of remote API requests.
"""

from openai import AsyncOpenAI

import os
from abc import ABC, abstractmethod

# Load dotenv needed if we have a .env file stored the variables there.
from dotenv import load_dotenv

load_dotenv()


# 1. Define a list of callable tools for the model
TOOLS = [
    {
        "type": "function",
        "name": "write_in_field",
        "description": "Fills an input field on the web page with a given value.",
        "parameters": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "description": "CSS field for the input field, e.g. input[name='email']",
                },
                "value": {
                    "type": "string",
                    "description": "The value to enter into the field",
                },
            },
            "required": ["field", "value"],
        },
    },
    {
        "type": "function",
        "name": "click_element",
        "description": "Clicks an element on the web page, e.g. a submit button. This must always be the LAST action, after all fields are filled.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector for the element to click",
                }
            },
            "required": ["selector"],
        },
    },
]


async def write_in_field(page, field: str, value: str, as_human: bool = False) -> bool:
    """Write the value in the field, (Value : some_username) (Field: #username)"""
    """ Something like: write_in_field(some_username, #username)"""

    if not page:
        raise ValueError("page is required")

    # Check if the field exists before writing in it
    locator = page.locator(field)
    if await locator.count() == 0:
        return False

    if as_human:
        await page.click(field)
        await page.type(field, value, delay=110)
    else:
        await page.fill(field, value)

    return True


async def click_element(page, selector: str):
    """This gonna be used so that a button or a selector getting clicked
    Like Maybe after setting the username and and password we wanna click
    submit so we can use this to click to this submit button
    """

    if not page:
        raise ValueError("page is required")

    # Check if the selector exists before clicking
    element = page.locator(selector)
    if await element.count() == 0:
        return False

    await page.click(selector)
    return True


class AIClientBase(ABC):
    @abstractmethod
    async def ask_client(
        self,
        user_input: str,
        instructions: str,
        tools=None,
    ): ...


class AIClient(AIClientBase):
    def __init__(self):
        api_key = os.getenv("SAIA_API_KEY")
        if not api_key:
            raise RuntimeError("AI API KEY IS NOT SET")

        self.client = AsyncOpenAI(
            api_key=api_key, base_url="https://chat-ai.academiccloud.de/v1"
        )
        self.model = "meta-llama-3.1-8b-instruct"

    async def ask_client(self, user_input: str, instructions: str, tools=None):
        params = {
            "model": self.model,
            "instructions": instructions,
            "input": user_input,
            "temperature": 0,
        }

        if tools is not None:
            params["tools"] = tools

        response = await self.client.responses.create(**params)
        return response
