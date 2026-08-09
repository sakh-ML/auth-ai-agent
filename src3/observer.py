"""
src/observer.py

Watches the onboarding portal and learns the participant's credentials.

This ALWAYS runs, in every AgentMode - per the study spec, the agent
learns the onboarding credentials even in Mode A / declined Mode B steps
("Agent lernt Onboarding in jedem Fall"). Only the login automation
later is mode-gated, not this.

No LLM is used here at all - we know the onboarding portal's exact DOM
(you control it), so this is 100% deterministic. That's also better for
credential handling: the raw password and TOTP secret never leave this
process, let alone get sent to any LLM API.
"""

from __future__ import annotations
import logging
from urllib.parse import parse_qsl

from context import AgentContext, OnboardingState
from portals import ONBOARDING_SELECTORS

logger = logging.getLogger(__name__)

# one general observer
# and one that inhertace from it, that for the study
# and one for the papier
# TODO

class OnboardingObserver:
    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self._password_listener_attached = False

    async def observe(self, page) -> None:
        url = page.url

        # port anpassen
        if "/set-password" in url or url.rstrip("/").endswith(":5001"):
            self._attach_password_capture(page)

        if "/setup-2fa" in url:
            await self._capture_totp_secret(page)

        if "/complete" in url and self.ctx.onboarding_state != OnboardingState.COMPLETE:
            self.ctx.onboarding_state = OnboardingState.COMPLETE
            logger.info(
                "Onboarding complete for %s. password_known=%s totp_known=%s",
                self.ctx.email,
                self.ctx.password is not None,
                self.ctx.totp_secret is not None,
            )

    def _attach_password_capture(self, page) -> None:
        """Reads the exact email/password the participant submitted, by
        inspecting the outgoing POST request body of the set-password
        form. This avoids racing against live DOM input values while
        they're still typing, and needs no LLM/DOM-diffing at all."""
        if self._password_listener_attached:
            return
        self._password_listener_attached = True

        def _handle_request(request):
            if request.method != "POST" or "/set-password" not in request.url:
                return
            post_data = request.post_data
            if not post_data:
                return
            form = dict(parse_qsl(post_data))
            email = form.get("email")
            password = form.get("new_password")
            if email:
                self.ctx.email = email
            if password:
                self.ctx.password = password
                self.ctx.onboarding_state = OnboardingState.PASSWORD_SET
                logger.info("Captured password for %s during onboarding", email)

        page.on("request", _handle_request)

    async def _capture_totp_secret(self, page) -> None:
        selector = ONBOARDING_SELECTORS["totp_secret_text"]
        try:
            await page.wait_for_selector(selector, timeout=5000)
            secret = await page.locator(selector).text_content()
        except Exception as e:
            logger.warning(
                "Could not read TOTP secret via selector %r - check "
                "ONBOARDING_SELECTORS['totp_secret_text'] in portals.py "
                "against setup_2fa.html: %s",
                selector, e,
            )
            return

        if secret:
            self.ctx.totp_secret = secret.strip()
            self.ctx.onboarding_state = OnboardingState.TOTP_SECRET_CAPTURED
            logger.info("Captured TOTP secret during onboarding")
