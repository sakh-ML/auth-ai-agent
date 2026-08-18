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


async def run(start_url: str, mode: AgentMode) -> None:
    """Initializes the AgentContext and Playwright browser, and binds the Orchestrator to page loads."""

    logger = logging.getLogger(__name__)

    logger.info(f"Running Agent in mode: {mode.name.lower().replace('_', '')}")

    ctx = AgentContext(mode=mode)
    orchestrator = Orchestrator(ctx)

    async with async_playwright() as playwright:
        logger.info("Starting browser")
        browser = await playwright.firefox.launch(headless=False)
        page = await browser.new_page()

        page.on(
            "load",
            lambda p=page: asyncio.create_task(orchestrator.on_page_load(p)),
        )

        logger.info(f"Opening start URL: {start_url}")
        await page.goto(start_url)

        # TODO :- listen for exiting page/browser
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Exiting...")
        finally:
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
        default="http://31.70.108.229/set-password",
        help="Onboarding portal start URL",
    )
    args = parser.parse_args()

    setup_logging(args.participant_id, args.mode)

    asyncio.run(run(args.url, MODE_MAP[args.mode]))


if __name__ == "__main__":
    main()
