"""
src/observer.py

Defines the abstract BaseObserver, alongside the Deterministic OnboardingObserver
and the powerful AIGenericObserver.
"""

import json
import logging
from abc import ABC, abstractmethod
from urllib.parse import parse_qsl

from context import AgentContext
from clean_dom import get_page_dom
from client import AIClient

logger = logging.getLogger(__name__)

# ==========================================
# 1. ABSTRACT BASE CLASS
# ==========================================

class BaseObserver(ABC):
    """
    Abstract base class for all browser observers.
    Ensures every observer implements the `observe` method.
    """
    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self._attached_pages = set()

    @abstractmethod
    async def observe(self, page) -> None:
        """
        Analyzes the page and attaches listeners if necessary to capture
        credentials or 2FA secrets.
        """
        pass


# ==========================================
# 2. AI GENERIC OBSERVER (Dynamic / Wild Web)
# ==========================================

# We define a specific tool just for the AI observer to use.
# It tells the AI to report back the exact form field 'name' attributes.
OBSERVER_AI_TOOLS = [
    {
        "type": "function",
        "name": "report_login_fields",
        "description": "Call this if a login or registration form is found to report the input 'name' attributes.",
        "parameters": {
            "type": "object",
            "properties": {
                "is_login_page": {
                    "type": "boolean",
                    "description": "True if a login or registration form is on the page."
                },
                "username_name_attr": {
                    "type": "string",
                    "description": "The exact 'name' attribute of the username/email input field."
                },
                "password_name_attr": {
                    "type": "string",
                    "description": "The exact 'name' attribute of the password input field."
                }
            },
            "required": ["is_login_page", "username_name_attr", "password_name_attr"]
        }
    }
]

class AIGenericObserver(BaseObserver):
    """
    Uses OpenAI to analyze unknown pages. If it detects a login form,
    it learns what field names to look for, and attaches a network listener
    to capture the POST request containing the credentials.
    """

    async def observe(self, page) -> None:
        page_id = id(page)
        if page_id in self._attached_pages:
            return

        logger.info(f"AIGenericObserver: Asking AI to analyze {page.url}")
        dom = await get_page_dom(page)
        
        instructions = (
            "You are a web parsing agent. Your job is to look at the DOM and determine "
            "if there is a login or registration form. If there is, you MUST use the "
            "`report_login_fields` tool to output the 'name' attributes of the username "
            "and password fields. Do not guess, only extract what is in the DOM."
        )

        try:
            client = AIClient()
            response = client.ask_client(
                input=[{"role": "user", "content": f"---- DOM ----\n{dom}\n---- END ----"}],
                instructions=instructions,
                tools=OBSERVER_AI_TOOLS
            )

            # Check if the AI called our reporting tool
            for item in response.output:
                if item.type == "function_call" and item.name == "report_login_fields":
                    args = json.loads(item.arguments)
                    
                    if args.get("is_login_page"):
                        user_attr = args.get("username_name_attr")
                        pass_attr = args.get("password_name_attr")
                        
                        logger.info(
                            f"AI detected login form. Expected POST fields: user='{user_attr}', pass='{pass_attr}'"
                        )
                        
                        # Attach the network listener with the AI's extracted field names
                        self._attach_network_listener(page, user_attr, pass_attr)
                        self._attached_pages.add(page_id)
                        return

            logger.debug("AIGenericObserver: AI did not detect a login form.")

        except Exception as e:
            logger.error(f"AIGenericObserver failed: {e}")

    def _attach_network_listener(self, page, user_field: str, pass_field: str) -> None:
        """Listens for the exact POST request expected by the AI."""
        
        def handle_request(request):
            if request.method != "POST":
                return
            
            post_data = request.post_data
            if not post_data:
                return

            try:
                # Parse the outgoing form data
                form_data = dict(parse_qsl(post_data))
                
                # Check if the AI's predicted fields are in the submission
                if user_field in form_data and pass_field in form_data:
                    username = form_data[user_field]
                    password = form_data[pass_field]
                    
                    if username and password:
                        logger.info(f"AIGenericObserver: Captured credentials via POST interception!")
                        # Save securely to vault
                        self.ctx.vault.save_credentials(request.url, username, password)
            except Exception as e:
                logger.error(f"Error parsing request payload: {e}")

        # Bind the event listener to Playwright
        page.on("request", handle_request)
        logger.info("AIGenericObserver: Network listener attached successfully.")


# ==========================================
# 3. DETERMINISTIC OBSERVER (Controlled Study)
# ==========================================

class OnboardingObserver(BaseObserver):
    """
    Deterministic observer for the controlled study portals (e.g., localhost:5001).
    Since we know the exact DOM, we don't need the LLM here.
    """
    
    async def observe(self, page) -> None:
        url = page.url
        page_id = id(page)
        
        if page_id in self._attached_pages:
            return

        if "/set-password" in url or url.rstrip("/").endswith(":5001"):
            self._attach_password_capture(page)
            self._attached_pages.add(page_id)

        if "/setup-2fa" in url:
            await self._capture_totp_secret(page)

    def _attach_password_capture(self, page) -> None:
        """Deterministic POST interceptor based on known API schema."""
        def _handle_request(request):
            if request.method != "POST" or "/set-password" not in request.url:
                return
            
            post_data = request.post_data
            if not post_data:
                return
                
            form = dict(parse_qsl(post_data))
            email = form.get("email")
            password = form.get("new_password")
            
            if email and password:
                self.ctx.vault.save_credentials(request.url, email, password)

        page.on("request", _handle_request)
        logger.info("OnboardingObserver: Deterministic listener attached.")

    async def _capture_totp_secret(self, page) -> None:
        """Deterministic TOTP reader based on known CSS selector."""
        selector = "#totp-secret" # (From portals.py ONBOARDING_SELECTORS)
        try:
            await page.wait_for_selector(selector, timeout=5000)
            secret = await page.locator(selector).text_content()
            if secret:
                self.ctx.vault.save_totp_secret(page.url, secret.strip())
        except Exception as e:
            logger.debug(f"Deterministic TOTP capture failed: {e}")
