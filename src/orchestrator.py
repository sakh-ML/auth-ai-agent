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
from typing import Callable

from context import AgentContext
from portals import identify_portal
from observer import BaseObserver
from automator import AIAutomator
from modes import make_policy
from ui import ask_user_yes_no
from portals import PortalType
from event import Event, log_event

logger = logging.getLogger(__name__)

# Fallback if the AgentContext doesn't define its own observe_timeout.
# Manual/Assisted study conditions may want a much longer value (a human
# needs time to type), configurable per-mode via ctx.observe_timeout.
DEFAULT_OBSERVE_TIMEOUT_SECONDS = 60.0


class Orchestrator:
    def __init__(
        self, ctx: AgentContext, observer: BaseObserver, automator: AIAutomator
    ):
        self.ctx = ctx
        self.observer = observer
        self.automator = automator

        self.policy = make_policy(ctx.mode)

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

    @staticmethod
    def _watch_for_navigation(page, original_url: str) -> tuple[asyncio.Event, Callable[[], None]]:
        """
        Returns (nav_event, unsubscribe). `nav_event` is SET the first time
        the page's main frame navigates away from `original_url`. Used as an
        early-exit signal for observation: if the user actually submits a
        login/2FA form and it succeeds, the browser navigates (e.g. to an
        inbox/dashboard) - we don't need to sit around for the full timeout
        just to notice that happened. Call `unsubscribe()` once done waiting
        to detach the listener again.
        """
        nav_event = asyncio.Event()

        def _on_frame_navigated(frame) -> None:
            if frame is page.main_frame and frame.url != original_url:
                nav_event.set()

        page.on("framenavigated", _on_frame_navigated)

        def unsubscribe() -> None:
            try:
                page.remove_listener("framenavigated", _on_frame_navigated)
            except Exception:
                # Best-effort; if this backend doesn't support removal the
                # listener just lives for the page's lifetime, which is
                # harmless since it only matches url != original_url once.
                pass

        return nav_event, unsubscribe

    async def _observe_then_log(
        self,
        page,
        url: str,
        finished_event: Event,
        interrupted_event: Event,
        has_result_fn,
        timeout: float | None = None,
    ) -> bool:
        """
        Runs observation and waits for it to REALLY finish before checking
        vault state and logging finished/interrupted. "Really finish" means
        one of:
          1. the observer's capture_event fires (credential/secret captured
             or the observer determined there's nothing to wait for), or
          2. the page navigates away from `url` (the strongest real-world
             signal that the user actually submitted the form and it went
             through), or
          3. a timeout elapses (fallback only - e.g. user closed the tab
             without the "close" hook firing, or just never acts).

        This is the single place where observe -> wait -> check -> log
        happens, so the timing bug can't quietly reappear in one of the
        several call sites that need this pattern.

        Returns True if `has_result_fn(url)` is true after waiting (i.e. the
        expected credential/TOTP secret actually showed up in time).
        """
        capture_event = await self.observer.observe(page)
        nav_event, unsubscribe_nav = self._watch_for_navigation(page, url)

        effective_timeout = (
            timeout
            if timeout is not None
            else getattr(self.ctx, "observe_timeout", DEFAULT_OBSERVE_TIMEOUT_SECONDS)
        )

        capture_task = asyncio.create_task(capture_event.wait())
        nav_task = asyncio.create_task(nav_event.wait())

        try:
            done, pending = await asyncio.wait(
                {capture_task, nav_task},
                timeout=effective_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()

            if not done:
                logger.warning(
                    f"Observation for {url} did not complete within "
                    f"{effective_timeout}s (no capture, no navigation); "
                    "proceeding with whatever the vault has now"
                )
            elif nav_task in done and capture_task not in done:
                logger.info(
                    f"Page navigated away from {url} before the capture "
                    "listener fired; treating as observation complete"
                )
        finally:
            unsubscribe_nav()

        got_it = has_result_fn(url)
        log_event(finished_event if got_it else interrupted_event)
        return got_it

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
                await self._observe_then_log(
                    page,
                    url,
                    Event.LOGIN_FINISHED,
                    Event.LOGIN_INTERRUPTED,
                    self.ctx.vault.has_credential_for,
                )
                return

            logger.info(f"Credentials found for: {url}")

            if portal_type == PortalType.ONBOARDING:
                logger.info(
                    f"ONBOARDING page detected: {url}. "
                    "Skipping auto-login and observing."
                )
                await self._observe_then_log(
                    page,
                    url,
                    Event.LOGIN_FINISHED,
                    Event.LOGIN_INTERRUPTED,
                    self.ctx.vault.has_credential_for,
                )
                return

            action_name = f"login for: {url}"

            async def ask(action_name: str) -> bool:
                question = f"Should I do {action_name}?"
                return await ask_user_yes_no(page, question)

            if not await self.policy.should_act(action_name, ask):
                logger.info(
                    f"Skipping automated login for {url}; continuing to observe for credentials"
                )
                await self._observe_then_log(
                    page,
                    url,
                    Event.LOGIN_FINISHED,
                    Event.LOGIN_INTERRUPTED,
                    self.ctx.vault.has_credential_for,
                )
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
                await self._observe_then_log(
                    page,
                    url,
                    Event.LOGIN_FINISHED,
                    Event.LOGIN_INTERRUPTED,
                    self.ctx.vault.has_credential_for,
                )
                return
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
                got_secret = await self._observe_then_log(
                    page,
                    url,
                    Event.TWO_FA_FINISHED,
                    Event.TWO_FA_INTERRUPTED,
                    self.ctx.vault.has_totp_secret_for,
                )
                if not got_secret:
                    return
                # We now have a secret, but _observe_then_log already logged
                # TWO_FA_FINISHED for the "we learned it" step. Fall through
                # to actually handle 2FA below using the freshly learned
                # secret, matching the original two-step behavior.

            logger.info("TOTP secret found; handling 2FA")

            action_name = f"2FA for: {url}"

            async def ask(action_name: str) -> bool:
                question = f"Should I do {action_name}?"
                return await ask_user_yes_no(page, question)

            if not await self.policy.should_act(action_name, ask):
                logger.info(f"Skipping automated 2FA for {url}")
                await self._observe_then_log(
                    page,
                    url,
                    Event.TWO_FA_FINISHED,
                    Event.TWO_FA_INTERRUPTED,
                    self.ctx.vault.has_totp_secret_for,
                )
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
                await self._observe_then_log(
                    page,
                    url,
                    Event.TWO_FA_FINISHED,
                    Event.TWO_FA_INTERRUPTED,
                    self.ctx.vault.has_totp_secret_for,
                )
                return
            log_event(Event.TWO_FA_FINISHED)

        logger.info(f"Url: {url} don't need 2fa")

        logger.info(f"Page is not a login or 2FA page; skipping: {url}")
