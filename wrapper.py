"""Wrapper to run the study agents for each participant.

Handles participant IDs, counterbalancing, agent execution,
and waiting between runs.
"""

import logging
import subprocess
import time

from src.utils.file_utils import read_file, write_to_file


WAITING_INTERVAL_BETWEEN_RUNS = 10
PARTICIPANT_ID_FILE_PATH = "participant_id.txt"

# Counterbalanced agent order, repeated every 4 participants.
participant_to_agent = {
    1: ["A", "B", "C1", "C2"],
    2: ["C1", "A", "C2", "B"],
    3: ["B", "C2", "A", "C1"],
    4: ["C2", "C1", "B", "A"],
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def get_participant_id():
    participant_id = read_file(PARTICIPANT_ID_FILE_PATH)

    if participant_id is None:
        participant_id = 1

    try:
        participant_id = int(participant_id)
    except ValueError:
        logger.info(
            f"Failed to convert {participant_id} to int. "
            "Setting participant ID to 1."
        )
        participant_id = 1

    return participant_id


def get_agent_order(participant_id: int):
    participant_mode = (participant_id - 1) % 4 + 1
    agents_order = participant_to_agent[participant_mode]

    if len(agents_order) != 4:
        raise AssertionError(
            f"Expected 4 different agent modes, but got: {len(agents_order)}"
        )
    return agents_order


def wait_for_start(participant_id: int, agent_mode: str) -> bool:
    """Wait for Enter before starting an agent.

    Returns False if the user presses Ctrl+C.
    """
    try:
        input(
            f"\nPress Enter to start "
            f"agent {agent_mode} for participant {participant_id}... "
        )
        return True
    except KeyboardInterrupt:
        print()
        logger.info("Stopped by user.")
        return False


def run_agent(
    participant_id: int,
    agent_mode: str,
    url: str | None = None,
) -> None:
    """Run the study agent for a specific participant and agent mode."""
    args = [
        "uv",
        "run",
        "src/main.py",
        "--participant_id",
        str(participant_id),
        "--mode",
        agent_mode,
    ]

    if url:
        args.extend(["--url", url])

    logger.info(f"Calling: {args}")

    subprocess.run(args, check=True)


def main() -> None:
    """Run the study continuously for each participant.

    Loads the next participant ID, runs the four agent modes
    in the assigned counterbalanced order, and saves the next
    participant ID when the program exits.
    """
    participant_id = get_participant_id()

    try:
        while True:
            agents_order = get_agent_order(participant_id)

            for agent_mode in agents_order:
                if not wait_for_start(participant_id, agent_mode):
                    return
                try:
                    run_agent(
                        participant_id=participant_id,
                        agent_mode=agent_mode,
                    )

                except Exception as e:
                    logger.exception(
                        f"Agent {agent_mode} failed "
                        f"for participant {participant_id}: {e}"
                    )

            participant_id += 1

    except Exception as e:
        logger.exception(f"Study wrapper stopped: {e}")

    finally:
        write_to_file(
            PARTICIPANT_ID_FILE_PATH,
            str(participant_id),
        )


if __name__ == "__main__":
    main()
