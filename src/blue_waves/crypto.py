"""Secrets-at-rest encryption (AES-256-GCM with a password-derived key).

Secrets are never written to disk in plaintext. A 32-byte key is derived from a
master password using PBKDF2-HMAC-SHA256 with a random per-file salt, and each
secret value is encrypted individually with AES-GCM (authenticated encryption).

Secrets are decrypted only in-memory for the lifetime of the process that
consumes them. The master password is read from the BLUE_WAVES_MASTER_PASSWORD
environment variable, with an optional in-process override for CLI/testing.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Any

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover - not importable in minimal env
    _CRYPTO_AVAILABLE = False


PBKDF2_ITERATIONS = 600_000
KEY_LEN = 32
SALT_LEN = 16
NONCE_LEN = 12
PREFIX = "enc:v1:"


class EncryptionUnavailableError(RuntimeError):
    """Raised when the `cryptography` package is not installed."""


class EncryptionDisabledError(RuntimeError):
    """Raised when a master password is required but not available."""


def _pbkdf2(password: bytes, salt: bytes, iterations: int) -> bytes:
    if not _CRYPTO_AVAILABLE:
        raise EncryptionUnavailableError("cryptography is not installed; cannot encrypt secrets")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LEN,
        salt=salt,
        iterations=iterations,
        backend=default_backend(),
    )
    return kdf.derive(password)


def derive_master_key(password: str, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> tuple[bytes, bytes]:
    """Derive a 32-byte AES key from a master password using PBKDF2-HMAC-SHA256.

    Returns (key, salt_used). A salt is generated if not supplied.
    """
    if not password:
        raise EncryptionDisabledError("a master password is required to encrypt secrets")
    salt = salt or os.urandom(SALT_LEN)
    key = _pbkdf2(password.encode("utf-8"), salt, iterations)
    return key, salt


class SecretCipher:
    """Encrypt/decrypt individual secret strings with AES-256-GCM."""

    def __init__(self, master_password: str) -> None:
        if not master_password:
            raise EncryptionDisabledError("BLUE_WAVES_MASTER_PASSWORD is not set")
        self._master_password = master_password
        # Derive once up front using a stable salt stored on each record; the
        # per-record salt is prepended to the ciphertext.
        self._key_cache: dict[bytes, bytes] = {}

    def _key_for(self, salt: bytes, iterations: int) -> bytes:
        cache_key = bytes(salt)
        if cache_key not in self._key_cache:
            key = _pbkdf2(self._master_password.encode("utf-8"), salt, iterations)
            self._key_cache[cache_key] = key
        return self._key_cache[cache_key]

    def encrypt(self, value: str, master_salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> str:
        """Encrypt a string, returning 'enc:v1:<base64(salt)<base64(nonce+ciphertext)>'."""
        if not _CRYPTO_AVAILABLE:
            raise EncryptionUnavailableError("cryptography is not installed; cannot encrypt secrets")
        if not value:
            return ""
        key = self._key_for(master_salt, iterations)
        nonce = os.urandom(NONCE_LEN)
        ciphertext = AESGCM(key).encrypt(nonce, value.encode("utf-8"), None)
        enc = base64.b64encode(master_salt + nonce + ciphertext).decode("ascii")
        return f"{PREFIX}{iterations}:{enc}"

    def decrypt(self, blob: str) -> str:
        """Decrypt a string produced by :meth:`encrypt`. Plain strings pass through."""
        if not blob:
            return ""
        if not blob.startswith(PREFIX):
            return blob
        body = blob[len(PREFIX):]
        iterations_str, payload = body.split(":", 1)
        iterations = int(iterations_str)
        raw = base64.b64decode(payload)
        master_salt = raw[:SALT_LEN]
        nonce = raw[SALT_LEN : SALT_LEN + NONCE_LEN]
        ciphertext = raw[SALT_LEN + NONCE_LEN :]
        if not _CRYPTO_AVAILABLE:
            raise EncryptionUnavailableError("cryptography is not installed; cannot decrypt secrets")
        key = self._key_for(master_salt, iterations)
        plain = AESGCM(key).decrypt(nonce, ciphertext, None)
        return plain.decode("utf-8")


# Set of keys inside a connection record that are treated as secrets.
SECRET_KEYS = {
    "api_key",
    "access_token",
    "refresh_token",
    "client_secret",
    "oauth_state",
}

# A non-secret salt persisted alongside the store so records can encrypt with a
# stable salt without storing the password itself.
STORE_SALT_FILE = "connections.salt"


def get_master_password(env_value: str | None = None, override: str | None = None) -> str:
    """Resolve the master password, preferring explicit override, then env."""
    password = override or env_value or os.environ.get("BLUE_WAVES_MASTER_PASSWORD", "")
    if not password:
        raise EncryptionDisabledError(
            "BLUE_WAVES_MASTER_PASSWORD is not set; set it to enable secret encryption"
        )
    return password


def encrypt_value(cipher: SecretCipher, key: str, value: Any, master_salt: bytes) -> Any:
    """Encrypt value if the key is a secret and the value is a string."""
    if key in SECRET_KEYS and isinstance(value, str) and value:
        return cipher.encrypt(value, master_salt)
    return value


def decrypt_value(cipher: SecretCipher, value: Any) -> Any:
    """Decrypt value if it is an encrypted blob string."""
    if isinstance(value, str) and value.startswith(PREFIX):
        return cipher.decrypt(value)
    return value
