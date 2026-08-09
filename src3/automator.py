"""
src/automator.py

Performs the actual login (and, if needed, TOTP submission) on the four
post-onboarding portals (mail / lsf / moodle / boss), using the
credentials OnboardingObserver learned.

Deterministic selectors (portals.py) are tried first, since we control
these 5 apps and their DOM is fixed. The LLM fallback (llm_fallback.py)
only kicks in if a selector is missing or the deterministic attempt
fails - e.g. before you've filled in the real mail/lsf/moodle/boss
selectors. The fallback uses the credential-placeholder pattern, so real
values are still never sent to the LLM.
"""

from __future__ import annotations
import logging
import pyotp

from context import AgentContext, PortalType
from portals import LOGIN_SELECTORS, TOTP_SELECTORS
from llm_fallback import llm_login_fallback, llm_totp_fallback

logger = logging.getLogger(__name__)


async def _type_into(page, selector: str, value: str, human_like: bool) -> None:
    if human_like:
        await page.click(selector)
        await page.type(selector, value, delay=110)  # C1: human-like pacing
    else:
        await page.fill(selector, value)  # C2 / default: instant


class PortalAutomator:
    def __init__(self, ctx: AgentContext, use_llm_fallback: bool = True):
        self.ctx = ctx
        self.use_llm_fallback = use_llm_fallback

    async def login(self, page, portal: PortalType, human_like: bool = False) -> bool:
        if not self.ctx.credentials_known():
            logger.warning("Cannot log in to %s: credentials not yet known", portal.value)
            return False

        selectors = LOGIN_SELECTORS.get(portal)
        if selectors and await self._deterministic_login(page, selectors, human_like):
            self.ctx.mark_logged_in(portal)
            return True

        if self.use_llm_fallback:
            logger.info("Falling back to LLM login handler for %s", portal.value)
            try:
                await llm_login_fallback(page, self.ctx)
                self.ctx.mark_logged_in(portal)
                return True
            except Exception as e:
                logger.error("LLM login fallback failed for %s: %s", portal.value, e)
                return False

        logger.error("Login failed for %s and LLM fallback is disabled", portal.value)
        return False

    async def _deterministic_login(self, page, selectors: dict, human_like: bool) -> bool:
        try:
            await page.wait_for_selector(selectors["username"], timeout=5000)
            await _type_into(page, selectors["username"], self.ctx.email, human_like)
            await _type_into(page, selectors["password"], self.ctx.password, human_like)
            await page.click(selectors["submit"])
            return True
        except Exception as e:
            logger.warning("Deterministic login selectors failed (%s) - check portals.py", e)
            return False

    async def submit_totp(self, page, portal: PortalType, human_like: bool = False) -> bool:
        """Call this if a portal shows its own 2FA/code-entry step after
        password login (separate from the onboarding TOTP setup)."""
        if not self.ctx.totp_secret:
            logger.warning("No TOTP secret known yet, cannot generate a code")
            return False

        selectors = TOTP_SELECTORS.get(portal)
        if selectors:
            code = pyotp.TOTP(self.ctx.totp_secret).now()
            try:
                await _type_into(page, selectors["code"], code, human_like)
                await page.click(selectors["submit"])
                return True
            except Exception as e:
                logger.warning(
                    "Deterministic TOTP selectors failed for %s (%s), trying LLM fallback",
                    portal.value, e,
                )

        if self.use_llm_fallback:
            try:
                await llm_totp_fallback(page, self.ctx)
                return True
            except Exception as e:
                logger.error("LLM TOTP fallback failed for %s: %s", portal.value, e)
                return False

        return False