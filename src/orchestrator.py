"""
Serves as the central page-load handler and workflow controller.

Orchestrates the lifecycle of a page visit by evaluating the URL, delegating
DOM classification to the Automator, executing network observation for credentials,
and strictly enforcing the active ModePolicy before automating logins or 2FA.
Prevents duplicate processing using an async lock and in-flight tracking.
"""

from __future__ import annotations
import logging
import asyncio

from context import AgentContext
from portals import identify_portal
from observer import AIGenericObserver
from automator import AIAutomator
from modes import make_policy
from ui import ask_user_yes_no
from portals import PortalType

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self.policy = make_policy(ctx.mode)
        self.observer = AIGenericObserver(ctx)

        self.automator = AIAutomator(ctx)
        self._on_flight: set[str] = set()

        self._lock = asyncio.Lock()

    async def on_page_load(self, page) -> None:

        # Wait for the page to completely finish loading and network to settle
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception as e:
            logger.warning(f"Network didn't idle in time, proceeding anyway: {e}")

        async with self._lock:
            url = page.url
            # portal = identify_portal(url)

            # if not portal:
            #    logger.warning(f"Ignoring non-study URL: {url}")
            #    return

            if url in self._on_flight:
                logger.info(f"Already processing {url}, ignoring duplicate load event")
                return

            self._on_flight.add(url)

            try:
                await self._handle_page(page, url)
            finally:
                self._on_flight.remove(url)

    async def _handle_page(self, page, url) -> None:
        """
        Core logic for evaluating a loaded page. Checks for login or 2FA states,
        verifies vault credentials, enforces user permission policies, and triggers
        the AIAutomator or AIGenericObserver accordingly.
        """

        logger.info(f"Checking if {url} needs login")

        if not await self.automator.is_login_page(page):
            logger.info(f"Url: {url} don't require login")
        else:
            logger.info("Login page found")

            if not self.ctx.vault.has_credential_for(url):
                logger.info(
                    f"No login credentials found for {url}; observing the website for credentials"
                )
                await self.observer.observe(page)
                return

            logger.info(f"Credentials found for: {url}")

            # Ignore set-password pages; auto-login is not allowed there.
            if "/set-password" in url:
                logger.info(f"Skipping auto-login on set-password page: {url}")
                return

            action_name = f"login for: {url}"

            async def ask(action_name: str) -> bool:
                question = f"Should I do {action_name}?"
                return await ask_user_yes_no(page, question)

            if not await self.policy.should_act(action_name, ask):
                logger.info(
                    f"Skipping automated login for {url}; continuing to observe for credentials"
                )
                await self.observer.observe(page)
                return

            logger.info("Handling login ...")

            await self.policy.before_action(page)
            try:
                human_like = self.policy.human_like_typing
                completed = await self.policy.run_interruptible(
                    self.automator.login(page, human_like=human_like)
                )
            finally:
                await self.policy.after_action(page)

            if completed is False:
                # Either a field couldn't be resolved, or the user hit
                # Escape. Either way, fall back to observing so we can still
                # learn from the page being completed manually.
                logger.info(
                    f"Automated login for {url} did not complete; observing instead"
                )
                await self.observer.observe(page)
            return

        logger.info(f"Checking if {url} needs 2FA")

        if not await self.automator.is_2fa_page(page):
            logger.info(f"Url: {url} don't need 2fa")
        else:
            logger.info(f"Page requires 2FA: {url}")

            if not self.ctx.vault.has_totp_secret_for(url):
                logger.info(
                    f"No TOTP secret found for {url} yet; observing so we can "
                    "learn it (e.g. from a setup/QR page) for next time"
                )
                await self.observer.observe(page)

                # Second check after observing, if we got a the totp_secrect
                if not self.ctx.vault.has_totp_secret_for(url):
                    return

            logger.info("TOTP secret found; handling 2FA")

            action_name = f"2FA for: {url}"

            async def ask(action_name: str) -> bool:
                question = f"Should I do {action_name}?"
                return await ask_user_yes_no(page, question)

            if not await self.policy.should_act(action_name, ask):
                logger.info(f"Skipping automated 2FA for {url}")
                await self.observer.observe(page)
                return

            await self.policy.before_action(page)
            try:
                human_like = self.policy.human_like_typing
                completed = await self.policy.run_interruptible(
                    self.automator.submit_2fa(page, human_like)
                )
            finally:
                await self.policy.after_action(page)

            if not completed:
                logger.info(
                    f"Automated 2FA for {url} did not complete; observing instead"
                )
                await self.observer.observe(page)
                return

        logger.info(f"Page is not a login or 2FA page; skipping: {url}")
