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

from context import AgentContext, PortalType
from portals import identify_portal
from observer import OnboardingObserver
from automator import PortalAutomator
from modes import make_policy
from ui import ask_user_yes_no

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, ctx: AgentContext, use_llm_fallback: bool = True):
        self.ctx = ctx
        self.policy = make_policy(ctx.mode)
        self.observer = OnboardingObserver(ctx)
        self.automator = PortalAutomator(ctx, use_llm_fallback=use_llm_fallback)

    async def on_page_load(self, page) -> None:
        url = page.url
        portal = identify_portal(url)

        if portal is None:
            logger.debug("Ignoring non-study URL: %s", url)
            return

        if portal is PortalType.ONBOARDING:
            await self.observer.observe(page)
            return

        await self._maybe_login(page, portal)

    async def _maybe_login(self, page, portal: PortalType) -> None:
        if self.ctx.is_logged_in(portal):
            return
        if not self.ctx.credentials_known():
            logger.info("Credentials not known yet, skipping login for %s", portal.value)
            return

        action_name = f"log in to {portal.value}"

        async def ask(_name: str) -> bool:
            return await ask_user_yes_no(
                page, f"Soll ich den Login fuer {portal.value} durchfuehren?"
            )

        if not await self.policy.should_act(action_name, ask):
            logger.info("Skipping automated login for %s (mode/user declined)", portal.value)
            return

        await self.policy.before_action(page)
        try:
            human_like = self.policy.human_like_typing
            await self.policy.run_interruptible(
                self.automator.login(page, portal, human_like=human_like)
            )
        finally:
            await self.policy.after_action(page)