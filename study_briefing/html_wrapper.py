"""Wrapper to run the study agents for each participant."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import argparse
from pathlib import Path

from study_server import StudyServer

TARGET_URL = "http://onboarding.tu-dortmund-services.de/"
MODES = ["A", "B", "C1", "C2"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Counterbalanced agent order.
participant_to_agent = {
    1: ["A", "B", "C1", "C2"],
    2: ["C1", "A", "C2", "B"],
    3: ["B", "C2", "A", "C1"],
    4: ["C2", "C1", "B", "A"],
}

logging.basicConfig(
    level=logging.INFO,
    format=("%(asctime)s | " "%(levelname)s | " "%(name)s | " "%(message)s"),
)
logger = logging.getLogger(__name__)


def get_agent_order(participant_id: int) -> list[str]:
    participant_mode = ((participant_id - 1) % 4) + 1
    agents_order = participant_to_agent[participant_mode]

    if len(agents_order) != 4:
        raise AssertionError(f"Expected 4 agent modes, but got: {len(agents_order)}")
    return agents_order


def log_current_run(participant_id: int, mode: str):
    logger.info(
        "Participant %s current agent run: %s",
        participant_id,
        mode,
    )


def log_agent_order(participant_id: int, mode: str | None):
    if mode:
        order_agents = [mode]
    else:
        order_agents = get_agent_order(participant_id)

    logger.info(
        "Participant %s has agent order: %s",
        participant_id,
        order_agents,
    )


def run_agent(participant_id: int, agent_mode: str) -> None:
    """Start the existing src/main.py."""
    args = [
        "uv",
        "run",
        "src/main.py",
        "--participant_id",
        str(participant_id),
        "--mode",
        agent_mode,
        "--url",
        TARGET_URL,
    ]

    logger.info("Starting agent: %s", " ".join(args))
    subprocess.run(args, check=True, cwd=PROJECT_ROOT)


async def show_start_page() -> bool:
    """Show the local page and wait until Start is clicked."""
    started = asyncio.Event()
    loop = asyncio.get_running_loop()

    def on_start() -> None:
        loop.call_soon_threadsafe(started.set)

    server = StudyServer(on_start)
    server.start()

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            logger.info("Opening local study briefing...")
            logger.info("Starting browser")

            browser = await playwright.firefox.launch(
                headless=False, args=["--start-maximized"]
            )
            context = await browser.new_context(no_viewport=True)
            page = await context.new_page()

            await page.goto("http://127.0.0.1:8000/")
            logger.info("Waiting for participant to click 'Studie starten'...")

            # Wait for the user to click the button
            await started.wait()

            logger.info("Participant clicked start!")
            await asyncio.sleep(1)
            await browser.close()
            return True

    except KeyboardInterrupt:
        logger.info("Study briefing stopped.")
        return False
    finally:
        server.stop()


def run_agents(participant_id: int, mode: str):

    try:
        # Show the start page and waiting for the participant to start the study
        result = asyncio.run(show_start_page())

        # If the browser was closed or interrupted before starting
        if not result:
            return

        # Single mode execution from CLI
        if mode:
            log_current_run(participant_id=participant_id, mode=mode)
            run_agent(participant_id=participant_id, agent_mode=mode)
            return

        # Otherwise, run the full order
        agents_order = get_agent_order(participant_id)

        # Run first agent
        log_current_run(participant_id=participant_id, mode=agents_order[0])
        run_agent(
            participant_id=participant_id,
            agent_mode=agents_order[0],
        )

        # Run remaining agents, waiting for briefing start page before each
        for agent_mode in agents_order[1:]:
            # Show the start page and waiting for the participant to start the study
            result = asyncio.run(show_start_page())

            # If the browser was closed or interrupted before starting
            if not result:
                return

            log_current_run(participant_id=participant_id, mode=agent_mode)
            run_agent(
                participant_id=participant_id,
                agent_mode=agent_mode,
            )

    except KeyboardInterrupt:
        logger.info("Study stopped by user.")
    except Exception as e:
        logger.exception("Study wrapper stopped: %s", e)


def start(participant_id: int, mode: str | None):
    # Log Agent order before starting the start page
    log_agent_order(participant_id=participant_id, mode=mode)

    run_agents(participant_id, mode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Study automation agent")
    parser.add_argument(
        "--participant_id",
        type=int,
        required=True,
        help="Participant ID, used by the study",
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="",
        help="Agent mode for this session: A, B, C1, or C2",
    )
    parser.add_argument(
        "--url",
        default="http://onboarding.tu-dortmund-services.de/",
        help="Onboarding portal start URL",
    )

    args = parser.parse_args()

    participant_id = args.participant_id
    if participant_id < 0:
        raise RuntimeError("Participant-ID can't be negative")

    # Start the process with the provided CLI args
    start(participant_id, args.mode)


if __name__ == "__main__":
    main()
