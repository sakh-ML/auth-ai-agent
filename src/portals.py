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
PORTAL_URL_MAP: dict[str, PortalType] = {
    "onboarding.tu-dortmund-services.de": PortalType.ONBOARDING,
    "mail.tu-dortmund-services.de": PortalType.MAIL,
    "lsf.tu-dortmund-services.de": PortalType.LSF,
    "moodle.tu-dortmund-services.de": PortalType.MOODLE,
    "boss.tu-dortmund-services.de": PortalType.BOSS,
}


def identify_portal(url: str) -> PortalType | None:
    """Whitelist check. None means: not one of our 5 study portals,
    agent must do absolutely nothing there."""
    if not url or url == "about:blank" or url.startswith("firefox-error://"):
        return None
    parsed = urlparse(url)

    hostname = parsed.hostname
    hostname = hostname.lower()

    return PORTAL_URL_MAP.get(hostname)
