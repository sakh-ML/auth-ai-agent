"""
Serves as the central page-load handler and workflow controller. 

Orchestrates the lifecycle of a page visit by evaluating the URL, delegating 
DOM classification to the Automator, executing observation for credentials, 
and strictly enforcing the active ModePolicy before automating logins or 2FA.
"""

from __future__ import annotations
import logging

from context import AgentContext
from portals import identify_portal
from observer import AIGenericObserver
from automator import AIAutomator
from modes import make_policy
from ui import ask_user_yes_no

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self.policy = make_policy(ctx.mode)
        self.observer = AIGenericObserver(ctx)
        self.automator = AIAutomator(ctx)
        self._on_flight: set[str] = set()

    async def on_page_load(self, page) -> None:

        # Wait for the page to completely finish loading and network to settle
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception as e:
            logger.debug(f"Network didn't idle in time, proceeding anyway: {e}")

        url = page.url
        # portal = identify_portal(url)

        # if portal is None:
        #    logger.warning(f"Ignoring non-study URL: {url}")
        #    return

        if url in self._on_flight:
            logger.debug(f"Already processing {url}, ignoring duplicate load event")
            return

        self._on_flight.add(url)

        try:
            await self._handle_page(page, url)
        finally:
            self._on_flight.remove(url)

    async def _handle_page(self, page, url) -> str:
        logger.info(f"Checking if {url} needs login")

        if await self.automator.is_login_page(page):
            logger.info("Login page found")

            action_name = f"log in to {url}"

            async def ask(_name: str) -> bool:
                return await ask_user_yes_no(page, f"Should I do the login for: {url}?")

            if not await self.policy.should_act(action_name, ask):
                logger.info(
                    f"Skipping automated login for {url}; continuing to observe for credentials"
                )
                await self.observer.observe(page)
                return

            if not self.ctx.vault.has_credential_for(url):
                logger.info(
                    f"No login credentials found for {url}; observing the website for credentials"
                )
                await self.observer.observe(page)
                return

            logger.info("Login credentials found; handling login")

            await self.policy.before_action(page)
            try:
                human_like = self.policy.human_like_typing
                await self.policy.run_interruptible(
                    self.automator.login(page, human_like=human_like)
                )
            finally:
                await self.policy.after_action(page)
            return

        logger.info(f"Checking if {url} needs 2FA")

        if await self.automator.is_2fa_page(page):
            logger.info(f"Page requires 2FA: {url}")

            action_name = f"2fa in to {url}"

            async def ask(_name: str) -> bool:
                return await ask_user_yes_no(page, f"Should I do 2FA for: {url}?")

            if not await self.policy.should_act(action_name, ask):
                logger.info(f"Skipping automated 2FA for {url}")
                return

            if not self.ctx.vault.has_credential_for(url):
                logger.info(f"No 2FA credentials found for {url}; skipping")
                return

            logger.info("2FA credentials found; handling 2FA")

            await self.policy.before_action(page)
            try:
                human_like = self.policy.human_like_typing
                await self.policy.run_interruptible(
                    self.automator.submit_2fa(page, human_like)
                )
            finally:
                await self.policy.after_action(page)
            return

        logger.info(f"Page is not a login or 2FA page; skipping: {url}")
