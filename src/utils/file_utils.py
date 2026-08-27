import os
import logging

logger = logging.getLogger(__name__)


def read_file(path: str) -> str | None:
    if not isinstance(path, str):
        logger.error(f"File path: {path} is not a string")
        return None

    if not os.path.exists(path):
        logger.error(f"Path: {path} doesn't exist")
        return None

    if not os.path.isfile(path):
        logger.error(f"Path: {path} is not a file")
        return None

    with open(path) as file:
        return file.read()


def write_to_file(path: str, content: str) -> bool:
    """Overwrite the old content with the given content."""
    if not isinstance(path, str):
        logger.error(f"File path: {path} is not a string")
        return False

    if not isinstance(content, str):
        logger.error("Content is not a string")
        return False

    with open(path, "w") as file:
        file.write(content)

    return True
