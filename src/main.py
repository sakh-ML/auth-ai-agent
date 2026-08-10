"""
src/main.py

Entry point for a study session. Replaces the old on_page_load_openai
based main.py.

Usage (from repo root, matching your existing setup.sh/uv workflow):
    python src/main.py --mode A
    python src/main.py --mode B
    python src/main.py --mode C1
    python src/main.py --mode C2 --url http://localhost:5001/

The mode is fixed for the whole session by YOU (the experimenter) via
the CLI flag - participants never choose it themselves. This is the
only place AgentMode is picked; every other component just reacts to it.
"""

from __future__ import annotations
import argparse
import asyncio
import logging

from playwright.async_api import async_playwright

from context import AgentContext, AgentMode
from orchestrator import Orchestrator

# Get rid of the openai INFO post requests
logging.getLogger("httpx").setLevel(logging.WARNING)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MODE_MAP = {
    "A": AgentMode.MANUAL,
    "B": AgentMode.ASSISTED,
    "C1": AgentMode.AUTONOMOUS_SLOW,
    "C2": AgentMode.AUTONOMOUS_FAST,
}


async def run(start_url: str, mode: AgentMode) -> None:
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

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Exiting...")
        finally:
            await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Study automation agent")
    parser.add_argument(
        "--mode",
        choices=MODE_MAP.keys(),
        required=True,
        help="Agent mode for this session: A, B, C1, or C2",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:5001/",
        help="Onboarding portal start URL",
    )
    args = parser.parse_args()

    asyncio.run(run(args.url, MODE_MAP[args.mode]))


if __name__ == "__main__":
    main()
