"""
src/models.py

Defines internal data structures and agent modes.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AgentMode(Enum):
    MANUAL = "A"
    ASSISTED = "B"
    AUTONOMOUS_SLOW = "C1"
    AUTONOMOUS_FAST = "C2"


@dataclass
class Credential:
    username: Optional[str] = None
    password: Optional[str] = None
    totp_secret: Optional[str] = None

    def __repr__(self) -> str:
        pwd_status = "SET" if self.password else "EMPTY"
        totp_status = "SET" if self.totp_secret else "EMPTY"
        return f"<Credential user={self.username} pass={pwd_status} totp={totp_status}>"
