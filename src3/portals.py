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

#TODO : THIS SHOULD BE DELETED WE DONT NEED ANY DETERMINSTIC LOGIN WE USE THE AGENT TO DO THIS
# Deterministic login-form selectors per portal (post-onboarding logins).
# You have mail/lsf/moodle/boss templates in your GitLab repo - fill these
# in to match the real field names/ids. Until then, these are best-guess
# placeholders and PortalAutomator will fall back to the LLM if they're wrong.
LOGIN_SELECTORS: dict[PortalType, dict[str, str]] = {
    PortalType.MAIL: {
        "username": "input[name='username']",
        "password": "input[name='password']",
        "submit": "button[type='submit']",
    },
    PortalType.LSF: {
        "username": "input[name='username']",
        "password": "input[name='password']",
        "submit": "button[type='submit']",
    },
    PortalType.MOODLE: {
        "username": "input[name='username']",
        "password": "input[name='password']",
        "submit": "button[type='submit']",
    },
    PortalType.BOSS: {
        "username": "input[name='username']",
        "password": "input[name='password']",
        "submit": "button[type='submit']",
    },
}

#TODO : delete this section also
# Optional deterministic TOTP selectors, if the 4 portals also show a
# code-entry page after password login. Leave a portal out of this map
# to always use the LLM fallback for its 2FA step.
TOTP_SELECTORS: dict[PortalType, dict[str, str]] = {
    # PortalType.MAIL: {"code": "input[name='code']", "submit": "button[type='submit']"},
}

# From your onboarding/app.py + templates (set_password.html / setup_2fa.html).
# Double-check "totp_secret_text" against the real id/class that renders
# {{ secret }} as plain text in setup_2fa.html.
ONBOARDING_SELECTORS = {
    "email_field": "input[name='email']",
    "token_field": "input[name='token']",
    "new_password_field": "input[name='new_password']",
    "totp_secret_text": "#totp-secret",
    "totp_code_field": "input[name='code']",
}