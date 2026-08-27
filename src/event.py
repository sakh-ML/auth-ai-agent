import logging
from enum import Enum


logger = logging.getLogger(__name__)


class Event(Enum):
    LOGIN_STARTED = "LOGIN STARTED"
    LOGIN_FINISHED = "LOGIN FINISHED"
    TWO_FA_STARTED = "2FA STARTED"
    TWO_FA_FINISHED = "2FA FINISHED"


def log_event(event: Event):
    logger.info(event.value.lower())
