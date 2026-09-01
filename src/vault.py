"""
Provides persistent, multi-account credential storage.

Backed by a local JSON file, the CredentialVault automatically handles
saving, retrieving, and dynamically updating usernames, passwords, and
TOTP secrets for registrable base domains. Used heavily during observation
to incrementally build credentials and during automation to supply them.
"""

import json
import logging
from pathlib import Path
from urllib.parse import urlparse
import tldextract

from models import Credential

logger = logging.getLogger(__name__)


class CredentialVault:
    def __init__(self, storage_file: str = "credentials.json"):
        self.storage_path = Path(storage_file)

        # Store structure:
        # {
        #     "base_domain": Credential(...)
        # }
        self._store: dict[str, Credential] = {}

        self.load_from_disk()

    def _get_domain(self, url: str) -> str:
        """Extract the hostname from a URL."""
        parsed = urlparse(url)

        if not parsed.hostname:
            return "unknown_domain"

        return parsed.hostname

    def _get_base_domain(self, domain: str) -> str:
        """Extract the registrable base domain from a hostname."""
        result = tldextract.extract(domain)
        return f"{result.domain}.{result.suffix}"

    def load_from_disk(self) -> None:
        """Load credentials from the JSON file into memory."""
        if not self.storage_path.exists():
            logger.info(
                f"Vault: {self.storage_path} not found. Starting with empty vault."
            )
            self._store = {}
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._store = {}

            for base_domain, creds in data.items():
                self._store[base_domain] = Credential(
                    username=creds.get("username"),
                    password=creds.get("password"),
                    totp_secret=creds.get("totp_secret"),
                )

            logger.info(
                f"Vault: Loaded credentials for {len(self._store)} "
                f"base domains from {self.storage_path}"
            )

        except (json.JSONDecodeError, OSError, TypeError, AttributeError) as e:
            logger.error(
                f"Vault: Error reading credentials from {self.storage_path}: {e}"
            )

    def save_to_disk(self) -> None:
        """Atomically save in-memory credentials to the JSON file."""
        data = {}

        for base_domain, cred in self._store.items():
            data[base_domain] = {
                "username": cred.username,
                "password": cred.password,
                "totp_secret": cred.totp_secret,
            }

        try:
            temp_path = self.storage_path.with_suffix(".tmp")

            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            temp_path.replace(self.storage_path)

            logger.info(f"Vault: Updated credentials persisted to {self.storage_path}")

        except OSError as e:
            logger.error(
                f"Vault: Error writing credentials to {self.storage_path}: {e}"
            )

    def save_credentials(
        self,
        url: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Save newly observed credentials for a base domain incrementally."""
        if not username and not password:
            return

        domain = self._get_domain(url)
        base_domain = self._get_base_domain(domain)

        if base_domain not in self._store:
            self._store[base_domain] = Credential()

        credential = self._store[base_domain]

        updated = False
        if username and username != credential.username:
            credential.username = username
            updated = True

        if password and password != credential.password:
            credential.password = password
            updated = True

        if updated:
            logger.info(
                f"Vault: Updated credentials (user: {bool(username)}, pass: {bool(password)}) "
                f"on base domain [{base_domain}]"
            )
            self.save_to_disk()

    def update_credential(
        self,
        url: str,
        username: str | None = None,
        password: str | None = None,
        totp_secret: str | None = None,
    ) -> None:
        """Partially update or create credentials for a base domain."""
        if not any([username, password, totp_secret]):
            return

        domain = self._get_domain(url)
        base_domain = self._get_base_domain(domain)

        credential = self._store.get(base_domain)

        if credential is None:
            credential = Credential()
            self._store[base_domain] = credential

        updated_flags = []
        if username:
            credential.username = username
            updated_flags.append(f"user [{username}]")
        if password:
            credential.password = password
            updated_flags.append("pass [***]")
        if totp_secret:
            credential.totp_secret = totp_secret
            updated_flags.append("totp [***]")

        if updated_flags:
            logger.info(
                f"Vault: Updated credentials ({', '.join(updated_flags)}) on base domain [{base_domain}]"
            )
            self.save_to_disk()

    def save_totp_secret(self, url: str, secret: str) -> None:
        """Save a learned 2FA/TOTP secret for a base domain."""
        domain = self._get_domain(url)
        base_domain = self._get_base_domain(domain)

        credential = self._store.get(base_domain)

        if credential is None:
            credential = Credential()
            self._store[base_domain] = credential

        credential.totp_secret = secret

        logger.info(f"Vault: Captured TOTP secret for base domain [{base_domain}]")

        self.save_to_disk()

    def get_credential(self, url: str) -> Credential | None:
        """Return the credential associated with the URL's base domain."""
        domain = self._get_domain(url)
        base_domain = self._get_base_domain(domain)
        return self._store.get(base_domain)

    def get_totp_secret(self, url: str) -> str | None:
        credential = self.get_credential(url)
        return credential.totp_secret if credential else None

    def has_credential_for(self, url: str) -> bool:
        """Return True if a complete credential exists for the base domain."""
        credential = self.get_credential(url)

        return bool(credential and credential.username and credential.password)

    def has_totp_secret_for(self, url: str) -> bool:
        """Return True if a TOTP secret exists for the URL's base domain."""
        credential = self.get_credential(url)

        return bool(credential and credential.totp_secret)
