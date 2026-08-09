"""
src/vault.py

Persistent, multi-account credential storage backed by a JSON file.
Automatically loads on startup and saves updates when observations occur.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from models import Credential

logger = logging.getLogger(__name__)


class CredentialVault:

    def __init__(self, storage_file: str = "credentials.json"):
        self.storage_path = Path(storage_file)
        # Store structure: { "domain": Credential }
        self._store: Dict[str, Credential] = {}
        self.load_from_disk()

    def _get_domain(self, url: str) -> str:
        """Extracts netloc (domain + port if present) from URL."""
        parsed = urlparse(url)
        if not parsed.netloc:
            return "unknown_domain"
        return parsed.netloc

    def load_from_disk(self) -> None:
        """Reads stored credentials from the JSON file into memory."""
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
            for domain, accounts in data.items():
                self._store[domain] = {}
                for acc in accounts:
                    username = acc.get("username")
                    self._store[domain] = Credential(
                        domain=domain,
                        username=username,
                        password=acc.get("password"),
                        totp_secret=acc.get("totp_secret"),
                    )
            logger.info(
                f"Vault: Loaded credentials for {len(self._store)} domains from {self.storage_path}"
            )
        except Exception as e:
            logger.error(
                f"Vault: Error reading credentials from {self.storage_path}: {e}"
            )

    def save_to_disk(self) -> None:
        """Flushes in-memory credentials to the JSON file atomically."""
        data = {}
        for domain, cred in self._store.items():
            data[domain] = [
                {
                    "username": cred.username,
                    "password": cred.password,
                    "totp_secret": cred.totp_secret,
                }
            ]

        try:
            temp_path = self.storage_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_path.replace(self.storage_path)
            logger.info(
                f"Vault: Updated credentials persisted to {self.storage_path}"
            )
        except Exception as e:
            logger.error(
                f"Vault: Error writing credentials to {self.storage_path}: {e}"
            )

    def save_credentials(
        self, url: str, username: Optional[str], password: Optional[str]
    ) -> None:
        """Saves newly observed user credentials to disk."""
        if not password:
            return

        domain = self._get_domain(url)

        if domain not in self._store:
            self._store[domain] = {}
                
        self._store[domain] = Credential(
            domain=domain, username=username, password=password
        )

        logger.info(
            f"Vault: Captured credentials for user [{username}] on domain [{domain}]"
        )
        self.save_to_disk()

    def save_totp_secret(
        self, url: str, secret: str
    ) -> None:
        """Saves a learned 2FA/TOTP secret for a domain/account."""
        domain = self._get_domain(url)

        if domain not in self._store:
            self._store[domain] = {}
        
        self._store[domain].totp_secret = secret
        logger.info(f"Vault: Captured TOTP secret for domain [{domain}]")
        self.save_to_disk()

    def get_credential(
        self, url: str
    ) -> Optional[Credential]:
        """Fetches stored credential matching URL domain and optional username."""
        domain = self._get_domain(url)
        credential = self._store.get(domain, {})

        if not credential:
            return None
        
        return credential


    def has_credential_for(self, url: str) -> bool:
        cred = self.get_credential(url)
        
        return bool(cred and cred.username and cred.password and cred.totp_secret)
