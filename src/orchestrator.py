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
from observer import BaseObserver
from automator import AIAutomator
from ui import ask_user_yes_no
from portals import PortalType
from event import Event, log_event

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self, ctx: AgentContext, observer: BaseObserver, automator: AIAutomator
    ):
        self.ctx = ctx
        self.observer = observer
        self.automator = automator

        self._on_flight: set[str] = set()
        self._lock = asyncio.Lock()

    async def on_page_load(self, page) -> None:
        url = page.url
        portal = identify_portal(url)
        if not portal:
            logger.warning(f"Ignoring non-study URL: {url}")
            return

        async with self._lock:
            if url in self._on_flight:
                logger.info(f"Already processing {url}, ignoring duplicate load event")
                return
            self._on_flight.add(url)

        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception as e:
            logger.warning(f"Network didn't idle in time, proceeding anyway: {e}")

        try:
            await self._handle_page(page, url)
        finally:
            async with self._lock:
                self._on_flight.remove(url)

    async def _handle_page(self, page, url) -> None:
        """
        Core logic for evaluating a loaded page. Checks for login or 2FA states,
        verifies vault credentials, enforces user permission policies, and triggers
        the AIAutomator or BaseObserver accordingly.
        """

        portal_type = identify_portal(url)

        logger.info(f"Checking if {url} needs login")

        if await self.automator.is_login_page(page):
            logger.info("Login page found")
            log_event(Event.LOGIN_STARTED)

            if not self.ctx.vault.has_credential_for(url):
                logger.info(
                    f"No login credentials found for {url}; observing the website for credentials"
                )
                await self.observer.observe(page)
                if not self.ctx.vault.has_credential_for(url):
                    log_event(Event.LOGIN_INTERRUPTED)
                    return
                log_event(Event.LOGIN_FINISHED)
                return

            logger.info(f"Credentials found for: {url}")

            if portal_type == PortalType.ONBOARDING:
                logger.info(
                    f"ONBOARDING page detected: {url}. "
                    "Skipping auto-login and observing."
                )
                await self.observer.observe(page)
                log_event(Event.LOGIN_FINISHED)
                return

            action_name = f"login for: \n {url}"

            async def ask(action_name: str) -> bool:
                question = f"Should I do {action_name}?"
                return await ask_user_yes_no(page, question)

            if not await self.ctx.policy.should_act(action_name, ask):
                logger.info(
                    f"Skipping automated login for {url}; continuing to observe for credentials"
                )
                await self.observer.observe(page)
                log_event(Event.LOGIN_FINISHED)
                return

            logger.info("Handling login ...")

            url_before_action = page.url
            # The Real login action
            completed = await self._login_action(page)

            # If login failed
            if not completed or not await self._check_url_changed(
                url_before_action, page
            ):
                logger.info(
                    f"Automated login for {url} did not complete; observing instead"
                )
                #old_credential = self.ctx.vault.get_credential(url)
                #await self.observer.observe(page)
                #new_credential = self.ctx.vault.get_credential(url)

                # Try again after failing and observing
                #if new_credential and old_credential != new_credential:
                #    if not await self._login_action(page):
                #        log_event(Event.LOGIN_INTERRUPTED)
                #        return
                #else:
                    #log_event(Event.LOGIN_INTERRUPTED)

            log_event(Event.LOGIN_FINISHED)
            return

        logger.info(f"Url: {url} don't require login")

        logger.info(f"Checking if {url} needs 2FA")

        if await self.automator.is_2fa_page(page):
            logger.info(f"Page requires 2FA: {url}")
            log_event(Event.TWO_FA_STARTED)

            if not self.ctx.vault.has_totp_secret_for(url):
                logger.info(
                    f"No TOTP secret found for {url} yet; observing so we can "
                    "learn it (e.g. from a setup/QR page) for next time"
                )
                await self.observer.observe(page)

                # Second check after observing, if we got a the totp_secrect
                if not self.ctx.vault.has_totp_secret_for(url):
                    log_event(Event.TWO_FA_INTERRUPTED)
                    return

                log_event(Event.TWO_FA_FINISHED)

            logger.info("TOTP secret found; handling 2FA")

            action_name = f"2FA for: \n {url}"

            async def ask(action_name: str) -> bool:
                question = f"Should I do {action_name}?"
                return await ask_user_yes_no(page, question)

            if not await self.ctx.policy.should_act(action_name, ask):
                logger.info(f"Skipping automated 2FA for {url}")
                await self.observer.observe(page)
                log_event(Event.TWO_FA_FINISHED)
                return

            url_before_action = page.url
            # The Real 2fa action
            completed = await self._2fa_action(page)

            # If 2fa failed
            if not completed or not await self._check_url_changed(
                url_before_action, page
            ):
                logger.info(
                    f"Automated 2FA for {url} did not complete; observing instead"
                )
                old_totp_secret = self.ctx.vault.get_totp_secret(url)
                await self.observer.observe(page)
                new_totp_secret = self.ctx.vault.get_totp_secret(url)
                
                # Try again after observing and failing
                if new_totp_secret and old_totp_secret != new_totp_secret:
                    if not await self._2fa_action(page):
                        log_event(Event.TWO_FA_INTERRUPTED)
                        return
                else:
                    log_event(Event.TWO_FA_INTERRUPTED)
            log_event(Event.TWO_FA_FINISHED)

        logger.info(f"Url: {url} don't need 2fa")

        logger.info(f"Page is not a login or 2FA page; skipping: {url}")

    async def _login_action(self, page):
        await self.ctx.policy.before_action(page)
        try:
            human_like = self.ctx.policy.human_like_typing
            completed = await self.ctx.policy.run_interruptible(
                self.automator.login(page, human_like=human_like)
            )
            return completed
        finally:
            await self.ctx.policy.after_action(page)

    async def _2fa_action(self, page):
        await self.ctx.policy.before_action(page)
        try:
            human_like = self.ctx.policy.human_like_typing
            completed = await self.ctx.policy.run_interruptible(
                self.automator.submit_2fa(page, human_like)
            )
            return completed
        finally:
            await self.ctx.policy.after_action(page)

    async def _check_url_changed(self, url_before_action: str, page) -> bool:
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception as e:
            logger.warning(f"Network didn't idle in time, proceeding anyway: {e}")

        url_after_action = page.url
        return url_after_action != url_before_action
