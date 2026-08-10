"""
src/orchestrator.py

The single page-load handler. Replaces on_page_load_openai from your
old main.py.

Flow per page load:
  1. identify_portal(url) -> whitelist check, ignore anything not ours
  2. onboarding portal      -> observe/learn (always, every mode)
  3. mail/lsf/moodle/boss   -> maybe log in (mode-gated via ModePolicy)
"""

from __future__ import annotations
import logging

from context import AgentContext
from portals import identify_portal
from observer import AIGenericObserver
from automator import AIAutomator
from modes import make_policy
from ui import ask_user_yes_no

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self.policy = make_policy(ctx.mode)
        self.observer = AIGenericObserver(ctx)
        self.automator = AIAutomator(ctx)

    async def on_page_load(self, page) -> None:

        # Wait for the page to completely finish loading and network to settle
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception as e:
            logger.debug(f"Network didn't idle in time, proceeding anyway: {e}")

        url = page.url
        #portal = identify_portal(url)

        # if portal is None:
        #    logger.warning(f"Ignoring non-study URL: {url}")
        #    return

        logger.info(f"CHECKING IF: {url} needs login")
        if await self.automator.is_login_page(page):
            logger.info("LOGIN PAGE FOUND")

            action_name = f"log in to {url}"

            async def ask(_name: str) -> bool:
                return await ask_user_yes_no(page, f"Should i do the login for: {url}?")

            if not await self.policy.should_act(action_name, ask):
                logger.info(
                    f"Skipping automated login for {url}, but observing new CREDS"
                )
                await self.observer.observe(page)
                return

            if not self.ctx.vault.has_credential_for(url):
                logger.info(
                    f"NO LOGIN CREDS FOR PAGE: {url}, observe the website for creds"
                )
                await self.observer.observe(page)
                return
            logger.info("CREDS WAS FOUND, HANDLING LOGIN")

            await self.policy.before_action(page)
            try:
                human_like = self.policy.human_like_typing
                await self.policy.run_interruptible(
                    self.automator.login(page, human_like=human_like)
                )
            finally:
                await self.policy.after_action(page)
            return

        logger.info(f"CHECKING IF: {url} needs 2fa auth")
        if await self.automator.is_2fa_page(page):
            logger.info(f"PAGE NEEDS 2FA: {url}")

            action_name = f"2fa in to {url}"

            async def ask(_name: str) -> bool:
                return await ask_user_yes_no(page, f"Should i do 2fa for: {url}?")

            if not await self.policy.should_act(action_name, ask):
                logger.info(f"Skipping automated 2fa auth for {url}")
                return

            if not self.ctx.vault.has_credential_for(url):
                logger.info(f"NO 2FA CREDS FOR PAGE: {url}, skipping ...")
                return
            logger.info("HANDLING 2FA CREDS WERE FOUND")

            await self.policy.before_action(page)
            try:
                human_like = self.policy.human_like_typing
                await self.policy.run_interruptible(
                    self.automator.submit_2fa(page, human_like)
                )
            finally:
                await self.policy.after_action(page)
            return

        logger.info(f"SKIP NOT A LOGIN OR 2FA PAGE: {url}")
