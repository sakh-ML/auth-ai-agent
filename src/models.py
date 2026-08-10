"""
Defines fundamental data structures and enumerations for the study agent. 

Contains the AgentMode enum representing the four experimental conditions 
(Manual, Assisted, Autonomous Slow, Autonomous Fast) and the Credential 
dataclass used to standardize in-memory authentication data.
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
