from __future__ import annotations

import json
import os
import secrets
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import crypto
from .crypto import (
    EncryptionDisabledError,
    SECRET_KEYS,
    STORE_SALT_FILE,
    SecretCipher,
    decrypt_value,
    encrypt_value,
)


# SSRF protection for OAuth token endpoint
ALLOWED_TOKEN_HOSTS = {
    "oauth2.googleapis.com",
    "accounts.google.com",
}

def _validate_token_url(url: str) -> None:
    """Validate URL to prevent SSRF for OAuth token endpoint."""
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise RuntimeError(f"Invalid URL scheme: {parsed.scheme}")
    
    hostname = parsed.hostname
    if not hostname:
        raise RuntimeError("URL missing hostname")
    
    # Allow localhost for local development
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return
    
    # Check against allowed hosts
    if hostname not in ALLOWED_TOKEN_HOSTS:
        raise RuntimeError(f"Host not allowed: {hostname}")


class ConnectionStore:
    """Local credential metadata store.

    Secret values (api keys, access/refresh tokens, client secrets) are encrypted
    at rest with AES-256-GCM using a master-password-derived key. They are never
    returned by the public API.
    """

    def __init__(self, root: Path, cipher: SecretCipher | None = None) -> None:
        self.path = root / "connections.json"
        self._cipher = cipher or _make_cipher_or_none(root)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Corrupt/noise file; treat as empty rather than crashing.
            return {}

    def _master_salt(self) -> bytes:
        """Return the persistent store salt, creating it if absent."""
        salt_path = self.path.parent / STORE_SALT_FILE
        if salt_path.exists():
            raw = salt_path.read_bytes()
            if len(raw) >= crypto.SALT_LEN:
                return raw[: crypto.SALT_LEN]
        salt = os.urandom(crypto.SALT_LEN)
        salt_path.write_bytes(salt)
        try:
            salt_path.chmod(0o600)
        except OSError:
            pass
        return salt

    def save(self, provider: str, values: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        current = data.get(provider, {})
        current.update(values)
        # Encrypt secret fields before persisting if a cipher is available.
        if self._cipher is not None:
            master_salt = self._master_salt()
            current = {
                k: encrypt_value(self._cipher, k, v, master_salt)
                for k, v in current.items()
            }
        data[provider] = current
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        return self.public(provider, self._decrypt_record(current))

    def get(self, provider: str) -> dict[str, Any]:
        record = self._read().get(provider, {})
        return self._decrypt_record(record)

    def _decrypt_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if self._cipher is None:
            return record
        out: dict[str, Any] = {}
        for k, v in record.items():
            if k in SECRET_KEYS:
                out[k] = decrypt_value(self._cipher, v)
            else:
                out[k] = v
        return out

    @staticmethod
    def public(provider: str, values: dict[str, Any]) -> dict[str, Any]:
        return {"provider": provider, "connected": bool(values.get("access_token") or values.get("api_key") or values.get("client_id")),
                "account": values.get("account"), "scopes": values.get("scopes", []),
                "configured": bool(values.get("client_id") or values.get("api_key"))}

    def status(self) -> dict[str, Any]:
        data = self._read()
        return {provider: self.public(provider, values) for provider, values in data.items()}

    def youtube_authorization_url(self, redirect_uri: str) -> str:
        config = self.get("youtube")
        if not config.get("client_id"):
            raise ValueError("YouTube OAuth client ID is not configured")
        state = secrets.token_urlsafe(24)
        self.save("youtube", {"oauth_state": state, "redirect_uri": redirect_uri})
        query = urllib.parse.urlencode({"client_id": config["client_id"], "redirect_uri": redirect_uri,
                                         "response_type": "code", "scope": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/yt-analytics.readonly",
                                         "access_type": "offline", "prompt": "consent", "state": state})
        return "https://accounts.google.com/o/oauth2/v2/auth?" + query

    def youtube_callback(self, code: str, state: str) -> dict[str, Any]:
        config = self.get("youtube")
        if not secrets.compare_digest(str(config.get("oauth_state", "")), state):
            raise ValueError("invalid YouTube OAuth state")
        payload = urllib.parse.urlencode({"code": code, "client_id": config["client_id"], "client_secret": config.get("client_secret", ""),
                                          "redirect_uri": config["redirect_uri"], "grant_type": "authorization_code"}).encode()
        token_url = "https://oauth2.googleapis.com/token"
        _validate_token_url(token_url)
        request = urllib.request.Request(token_url, data=payload, method="POST")
        with urllib.request.urlopen(request, timeout=15) as response:
            token = json.loads(response.read().decode())
        return self.save("youtube", {"access_token": token.get("access_token"), "refresh_token": token.get("refresh_token"),
                                      "scopes": ["youtube.upload", "yt-analytics.readonly"], "account": "authorized YouTube account", "oauth_state": None})


def _make_cipher_or_none(root: Path) -> SecretCipher | None:
    """Build a SecretCipher from BLUE_WAVES_MASTER_PASSWORD, or None to stay plaintext."""
    password = os.environ.get("BLUE_WAVES_MASTER_PASSWORD", "")
    if not password:
        return None
    try:
        return SecretCipher(password)
    except (EncryptionDisabledError, crypto.EncryptionUnavailableError):
        return None