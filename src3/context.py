"""
src/context.py

Core data model for the study agent.

One AgentContext instance lives for the whole browser session and is
passed into every other component (observer, automator, orchestrator).
Nothing else should hold its own copy of credentials or state.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto


class PortalType(Enum):
    ONBOARDING = "onboarding"
    MAIL = "mail"
    LSF = "lsf"
    MOODLE = "moodle"
    BOSS = "boss"


class OnboardingState(Enum):
    NOT_STARTED = auto()
    PASSWORD_SET = auto()
    TOTP_SECRET_CAPTURED = auto()
    COMPLETE = auto()  # credentials fully known -> ready for portal logins


class AgentMode(Enum):
    MANUAL = "A"            # no agent action at all
    ASSISTED = "B"          # ask the user before every action
    AUTONOMOUS_SLOW = "C1"  # act automatically, human-like pacing, interruptible (Escape)
    AUTONOMOUS_FAST = "C2"  # act automatically, instantly, no pacing


@dataclass
class AgentContext:
    mode: AgentMode = AgentMode.MANUAL

    email: str | None = None
    password: str | None = None
    totp_secret: str | None = None

    onboarding_state: OnboardingState = OnboardingState.NOT_STARTED
    logged_in_portals: set[PortalType] = field(default_factory=set)

    def credentials_known(self) -> bool:
        return self.password is not None and self.totp_secret is not None

    def is_logged_in(self, portal: PortalType) -> bool:
        return portal in self.logged_in_portals

    def mark_logged_in(self, portal: PortalType) -> None:
        self.logged_in_portals.add(portal)