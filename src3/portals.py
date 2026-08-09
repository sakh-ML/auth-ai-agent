"""
src/portals.py

Everything specific to "which of our 5 known Flask apps is this".

Replaces the old is_valid_url()/is_login_page() LLM-classifier approach.
We control every URL in this study, so we whitelist by (host, port)
instead of asking an LLM to guess generically.
"""

from __future__ import annotations
from urllib.parse import urlparse
from context import PortalType

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
