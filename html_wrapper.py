"""Wrapper to run the study agents for each participant."""

from __future__ import annotations

import asyncio
import logging
import subprocess

from src.utils.file_utils import read_file, write_to_file
from study_server import StudyServer


PARTICIPANT_ID_FILE_PATH = "participant_id.txt"

TARGET_URL = (
    "http://onboarding.tu-dortmund-services.de/"
)


# Counterbalanced agent order.
participant_to_agent = {
    1: ["A", "B", "C1", "C2"],
    2: ["C1", "A", "C2", "B"],
    3: ["B", "C2", "A", "C1"],
    4: ["C2", "C1", "B", "A"],
}


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(__name__)


def get_agent_order(
    participant_id: int,
) -> list[str]:

    participant_mode = (
        (participant_id - 1) % 4
    ) + 1

    agents_order = participant_to_agent[
        participant_mode
    ]

    if len(agents_order) != 4:
        raise AssertionError(
            f"Expected 4 agent modes, "
            f"but got: {len(agents_order)}"
        )

    return agents_order


def run_agent(
    participant_id: int,
    agent_mode: str,
) -> None:
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

    logger.info(
        "Starting agent: %s",
        " ".join(args),
    )

    subprocess.run(
        args,
        check=True,
    )


async def show_start_page() -> tuple[int, str] | None:
    """Show the local page and wait until Start is clicked."""

    started = asyncio.Event()

    selected: dict[str, int | str] = {}

    loop = asyncio.get_running_loop()


    def on_start(
        participant_id: int,
        mode: str,
    ) -> None:

        selected["participant_id"] = participant_id
        selected["mode"] = mode

        loop.call_soon_threadsafe(
            started.set
        )


    server = StudyServer(on_start)
    server.start()


    try:

        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:

            logger.info(
                "Opening local study briefing..."
            )
            
            logger.info("Starting browser")

            # Launch browser with start-maximized flag
            browser = await playwright.firefox.launch(
                headless=False, args=["--start-maximized"]
            )

            # Disable default fixed viewport so the site stretches to fill the screen
            context = await browser.new_context(no_viewport=True)
            page = await context.new_page()

            await page.goto(
                "http://127.0.0.1:8000/"
            )

            logger.info(
                "Waiting for participant "
                "to click 'Studie starten'..."
            )

            await started.wait()


            participant_id = int(
                selected["participant_id"]
            )

            mode = str(
                selected["mode"]
            )


            logger.info(
                "Participant %s selected mode %s",
                participant_id,
                mode,
            )


            await asyncio.sleep(1)

            await browser.close()

            return participant_id, mode


    except KeyboardInterrupt:

        logger.info(
            "Study briefing stopped."
        )

        return None


    finally:

        server.stop()
        
def wait_for_start(participant_id: int, agent_mode: str) -> bool:
    """Wait for Enter before starting an agent.

    Returns False if the user presses Ctrl+C.
    """
    try:
        input(
            f"\nPress Enter to start "
            f"agent {agent_mode} for participant {participant_id} ... "
        )
        return True
    except KeyboardInterrupt:
        print()
        logger.info("Stopped by user.")
        return False


def main() -> None:
    """Run the study continuously."""

    try:

        while True:            
            result = asyncio.run(
                show_start_page()
            )

            if result is None:
                return

            selected_participant_id, selected_mode = (
                result
            )
            
            if selected_mode:
                run_agent(
                    participant_id=selected_participant_id,
                    agent_mode=selected_mode
                )
                return

            agents_order = get_agent_order(
                selected_participant_id
            )
            
            logger.info(
                "Participant %s has agent order: %s",
                selected_participant_id,
                agents_order,
            )
            
            # Start the first agent immediately.
            run_agent(
                participant_id=selected_participant_id,
                agent_mode=agents_order[0],
            )

            # For all remaining agents, wait for the participant
            # before starting the next session.
            for agent_mode in agents_order[1:]:
                if not wait_for_start(
                    participant_id=selected_participant_id,
                    agent_mode=agent_mode,
                ):
                    return

                run_agent(
                    participant_id=selected_participant_id,
                    agent_mode=agent_mode,
                )

    except KeyboardInterrupt:

        logger.info(
            "Study stopped by user."
        )


    except Exception as e:

        logger.exception(
            "Study wrapper stopped: %s",
            e,
        )

if __name__ == "__main__":
    main()
