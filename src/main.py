"""
Entry point for the automation study session.

Initializes the Playwright browser, configures session logging, and parses CLI
arguments to set a fixed AgentMode (Manual, Assisted, or Autonomous) for the session.
Attaches the global Orchestrator to handle continuous page load events. The agent
mode is strictly controlled via the CLI to ensure consistency during experiments.
"""

from __future__ import annotations
import argparse
import asyncio
import logging

from playwright.async_api import async_playwright

from context import AgentContext, AgentMode
from orchestrator import Orchestrator
from logger import setup_logging
from client import AIClient
from observer import AIGenericObserver
from automator import AIAutomator

# Mute HTTP transport and API client debug logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)


MODE_MAP = {
    "A": AgentMode.MANUAL,
    "B": AgentMode.ASSISTED,
    "C1": AgentMode.AUTONOMOUS_SLOW,
    "C2": AgentMode.AUTONOMOUS_FAST,
}


def build_orchestrator(mode: AgentMode) -> Orchestrator:
    """Build and return an orchestrator configured for the given agent mode."""

    ai_client = AIClient()
    ctx = AgentContext(mode=mode, ai_client=ai_client)

    observer = AIGenericObserver(ctx)
    automator = AIAutomator(ctx)
    orchestrator = Orchestrator(ctx, observer, automator)

    return orchestrator


async def run(start_url: str, mode: AgentMode) -> None:
    """Initializes the AgentContext and Playwright browser, and binds the Orchestrator to page loads."""

    logger = logging.getLogger(__name__)

    logger.info(f"Running Agent in mode: {mode.name.upper().replace('_', '')}")

    orchestrator = build_orchestrator(mode)

    async with async_playwright() as playwright:
        logger.info("Starting browser")

        # Launch browser with start-maximized flag
        browser = await playwright.firefox.launch(
            headless=False, args=["--start-maximized"]
        )

        # Disable default fixed viewport so the site stretches to fill the screen
        context = await browser.new_context(no_viewport=True)
        page = await context.new_page()

        page.on(
            "load",
            lambda p=page: asyncio.create_task(orchestrator.on_page_load(p)),
        )

        logger.info(f"Opening start URL: {start_url}")
        await page.goto(start_url)

        # Listen for exiting page/browser without timing out
        try:
            logger.info(
                "Waiting indefinitely for the user to close the page/browser..."
            )

            # timeout=0 tells Playwright to NEVER time out.
            await page.wait_for_event("close", timeout=0)

        except KeyboardInterrupt:
            logger.info("Exiting via KeyboardInterrupt...")
        finally:
            logger.info("Page closed. Cleaning up...")
            if browser.is_connected():
                await browser.close()


def main() -> None:
    """Parses CLI arguments, sets up logging, and triggers the asynchronous run loop."""

    parser = argparse.ArgumentParser(description="Study automation agent")
    parser.add_argument(
        "--participant_id",
        type=int,
        required=True,
        help="Participant ID, used by the study",
    )
    parser.add_argument(
        "--mode",
        choices=MODE_MAP.keys(),
        required=True,
        help="Agent mode for this session: A, B, C1, or C2",
    )
    parser.add_argument(
        "--url",
        default="http://onboarding.tu-dortmund-services.de/",
        help="Onboarding portal start URL",
    )
    args = parser.parse_args()

    setup_logging(args.participant_id, args.mode)

    asyncio.run(run(args.url, MODE_MAP[args.mode]))


if __name__ == "__main__":
    main()
