"""
Manages study portal identification and whitelisting. 

Maps specific localhost ports to known Flask applications (Onboarding, Mail, 
LSF, Moodle, Boss) to strictly control which domains the agent is allowed 
to process during the study.
"""

from __future__ import annotations
from urllib.parse import urlparse
from enum import Enum


class PortalType(Enum):
    ONBOARDING = 0
    MAIL = 1
    LSF = 2
    MOODLE = 3
    BOSS = 4


# Adjust ports here to match how you actually launch the 5 Flask apps.
PORTAL_URL_MAP: dict[tuple[str | None, int | None], PortalType] = {
    ("localhost", 5001): PortalType.ONBOARDING,
    ("localhost", 5002): PortalType.MAIL,
    ("localhost", 5003): PortalType.LSF,
    ("localhost", 5004): PortalType.MOODLE,
    ("localhost", 5005): PortalType.BOSS,
    ("127.0.0.1", 5001): PortalType.ONBOARDING,
    ("127.0.0.1", 5002): PortalType.MAIL,
    ("127.0.0.1", 5003): PortalType.LSF,
    ("127.0.0.1", 5004): PortalType.MOODLE,
    ("127.0.0.1", 5005): PortalType.BOSS,
}


def identify_portal(url: str) -> PortalType | None:
    """Whitelist check. None means: not one of our 5 study portals,
    agent must do absolutely nothing there."""
    if not url or url == "about:blank" or url.startswith("firefox-error://"):
        return None
    parsed = urlparse(url)
    return PORTAL_URL_MAP.get((parsed.hostname, parsed.port))
