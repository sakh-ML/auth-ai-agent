"""
Contains observer implementations for capturing credentials and 2FA secrets.

Includes the abstract BaseObserver and the AIGenericObserver, which utilizes
an LLM to dynamically analyze DOM structures. It locates specific authentication
elements (like input fields and displayed TOTP secrets) and attaches network
listeners to intercept POST requests, automatically saving credentials to the vault.
"""

import json
import logging
from abc import ABC, abstractmethod
from urllib.parse import parse_qsl
from context import AgentContext
from clean_dom import get_page_dom
from prompts import get_prompt, get_system_prompt, Prompt, SystemPrompt

logger = logging.getLogger(__name__)


class BaseObserver(ABC):
    """
    Abstract base class for all browser observers.
    Ensures every observer implements the `observe` method.
    """

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self._attached_urls: set[str] = set()

    @abstractmethod
    async def observe(self, page) -> None:
        """
        Analyzes the page and attaches listeners if necessary to capture
        credentials or 2FA secrets.
        """
        pass


# We define a highly flexible tool to let the AI report EXACTLY what it sees,
# whether it's just a username, just a password, a 2FA code, or a combination or
# a also a css selector.
OBSERVER_AI_TOOLS = [
    {
        "type": "function",
        "name": "report_authentication_elements",
        "description": (
            "Report ALL authentication elements found in the DOM. "
            "This includes BOTH input fields (like username, password, or verification code inputs) "
            "AND displayed persistent TOTP secrets (like a manual entry key next to a QR code)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "input_fields": {
                    "type": "array",
                    "description": "List of input fields actually found in the DOM that the user types into.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name_attr": {
                                "type": "string",
                                "description": "The exact 'name' attribute of the input field.",
                            },
                            "field_purpose": {
                                "type": "string",
                                "enum": ["username", "password", "one_time_token"],
                                "description": "What the field is used for. Use 'one_time_token' for a single-use code.",
                            },
                        },
                        "required": ["name_attr", "field_purpose"],
                    },
                },
                "displayed_secret_css_selector": {
                    "type": "string",
                    "description": "The exact CSS selector (e.g., '.secret-box') of the DOM element whose text content IS a persistent, reusable 2FA secret (like a setup key). Return an empty string if not found.",
                },
            },
            "required": ["input_fields", "displayed_secret_css_selector"],
        },
    }
]


class AIGenericObserver(BaseObserver):
    """
    Uses an LLM to analyze authentication pages dynamically, identify the
    authentication input fields present in the DOM, and attach a flexible
    network listener for matching POST fields.
    """

    async def observe(self, page) -> None:
        if page.url in self._attached_urls:
            return
        self._attached_urls.add(page.url)

        logger.info(f"AIGenericObserver: Asking AI to analyze {page.url}")
        dom = await get_page_dom(page)

        observer_system_prompt = get_system_prompt(SystemPrompt.OBSERVER_SYSTEM_PROMPT)
        observer_prompt = get_prompt(Prompt.OBSERVER_PROMPT, dom)

        try:
            response = await self.ctx.ai_client.ask_client(
                input=[{"role": "user", "content": observer_prompt}],
                instructions=observer_system_prompt,
                tools=OBSERVER_AI_TOOLS,
            )

            detected_anything = False

            for item in response.output:
                if (
                    item.type != "function_call"
                    or item.name != "report_authentication_elements"
                ):
                    continue

                try:
                    args = json.loads(item.arguments)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.error(
                        f"AIGenericObserver: failed to decode tool arguments: {e}"
                    )
                    continue

                if not isinstance(args, dict):
                    continue

                # Handle the css selectors that picked from the agent
                css_selector = args.get("displayed_secret_css_selector", "")
                if (
                    css_selector
                    and isinstance(css_selector, str)
                    and css_selector.strip()
                ):
                    logger.info(
                        f"AI detected displayed secret at selector: {css_selector}"
                    )
                    try:
                        locator = page.locator(css_selector)
                        count = await locator.count()

                        if count > 0:
                            secret_text = await locator.first.text_content()
                            if secret_text:
                                self.ctx.vault.save_totp_secret(
                                    page.url, secret_text.strip()
                                )
                                logger.info(
                                    f"Successfully saved displayed TOTP secret via AI generic observer for {page.url}"
                                )
                                detected_anything = True
                        else:
                            logger.warning(
                                f"Selector '{css_selector}' returned 0 matching elements in the DOM."
                            )
                    except Exception as e:
                        logger.error(
                            f"Failed to read displayed secret from DOM: {e}",
                            exc_info=True,
                        )

                # Handle input fields (network listener)
                fields = args.get("input_fields", [])
                if isinstance(fields, str):
                    try:
                        fields = json.loads(fields)
                    except (json.JSONDecodeError, TypeError):
                        import ast

                        try:
                            fields = ast.literal_eval(fields)
                        except (ValueError, SyntaxError, TypeError):
                            continue

                field_mapping = {}
                for field in fields:
                    if not isinstance(field, dict):
                        continue
                    name_attr = field.get("name_attr")
                    purpose = field.get("field_purpose")
                    if name_attr and purpose:
                        field_mapping[name_attr] = purpose

                if field_mapping:
                    logger.info(
                        f"AI detected auth fields. Expected POST fields mapping: {field_mapping}"
                    )
                    self._attach_network_listener(page, field_mapping)
                    detected_anything = True

            if not detected_anything:
                logger.info(
                    "AIGenericObserver: AI did not detect any authentication fields or displayed secrets."
                )

        except Exception as e:
            logger.error(f"AIGenericObserver failed: {e}", exc_info=True)

    def _attach_network_listener(self, page, field_mapping: dict) -> None:
        """Listens for POST requests and flexibly captures any mapped fields it finds."""

        def handle_request(request):
            if request.method != "POST":
                return

            post_data = request.post_data
            if not post_data:
                return

            try:
                # Try parsing as JSON first
                try:
                    form_data = json.loads(post_data)
                except json.JSONDecodeError:
                    # Fallback to standard URL-encoded form data
                    form_data = dict(parse_qsl(post_data))

                captured = {}

                # Check if ANY of the AI's predicted fields are in the submission
                for name_attr, purpose in field_mapping.items():
                    if name_attr in form_data and form_data[name_attr]:
                        captured[purpose] = form_data[name_attr]

                if "one_time_token" in captured:
                    # Deliberately not persisted: a one-time token typed
                    # once alongside username/password is NOT a recurring
                    # TOTP secret, so we must never save it as one.
                    logger.info(
                        "AIGenericObserver: observed a one-time token field "
                        "- intentionally not saving it as totp_secret."
                    )

                if (
                    captured.get("username")
                    or captured.get("password")
                    or captured.get("totp_secret")
                ):
                    logger.info(
                        f"AIGenericObserver: Captured credentials via POST interception: "
                        f"{[k for k in captured if k != 'one_time_token']}"
                    )

                    # Update vault securely and flexibly based on what was caught.
                    # Note: one_time_token is intentionally never passed here.
                    self.ctx.vault.update_credential(
                        request.url,
                        username=captured.get("username"),
                        password=captured.get("password"),
                        totp_secret=captured.get("totp_secret"),
                    )
            except Exception as e:
                logger.error(f"Error parsing request payload: {e}")

        # Bind the event listener to Playwright
        page.on("request", handle_request)
        logger.info(
            "AIGenericObserver: Dynamic network listener attached successfully."
        )
