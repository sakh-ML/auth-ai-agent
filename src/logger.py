"""
Centralized logging configuration for the automation agent.

Creates participant- and mode-specific log directories and files, while
ensuring that each application run writes to a new log file rather than
overwriting or appending to a previous run.

Log messages are written to both the console and a run-specific file using
millisecond-precision timestamps.
"""

import logging
from pathlib import Path


def _next_available_log_file(log_dir: Path, base_name: str) -> Path:
    """Return a new log file path without overwriting an existing log."""
    candidate_log_file = log_dir / f"{base_name}.log"
    counter = 2
    while candidate_log_file.exists():
        candidate_log_file = log_dir / f"{base_name}_{counter}.log"
        counter += 1
    return candidate_log_file


def setup_logging(participant_id: int, mode: str, level: int = logging.INFO) -> None:
    """Configures the root logger once at application startup."""
    log_dir = Path(f"logs/participant_{participant_id}")
    log_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"participant_{participant_id}_{mode}"
    log_file = _next_available_log_file(log_dir, base_name)

    # Log with timestamp till millisecs
    formatter = logging.Formatter(
        "%(asctime)s:%(msecs)03d | %(levelname)s | %(name)s | %(message)s",
        datefmt="%d:%H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")

    # Apply formatter to handlers
    for handler in (console_handler, file_handler):
        handler.setFormatter(formatter)

    # force=True removes existing handlers
    logging.basicConfig(
        level=level, handlers=[console_handler, file_handler], force=True
    )
