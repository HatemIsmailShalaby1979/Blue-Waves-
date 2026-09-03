from __future__ import annotations

import json
import secrets
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


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
    """Local credential metadata store. Secret values are never returned by the API."""

    def __init__(self, root: Path) -> None:
        self.path = root / "connections.json"

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, provider: str, values: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        current = data.get(provider, {})
        current.update(values)
        data[provider] = current
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        return self.public(provider, current)

    def get(self, provider: str) -> dict[str, Any]:
        return self._read().get(provider, {})

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