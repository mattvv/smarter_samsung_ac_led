"""SmartThings OAuth helper.

SmartThings capped Personal Access Tokens at 24 hours for any token created
after 2025-01-01, so a PAT cannot be used as long-lived credentials any more.

This module uses a PAT exactly once -- to register an API_ONLY SmartApp -- and
from then on the integration authenticates with an OAuth refresh token, which
does not expire while it is in use. API_ONLY apps require no webhook, so this
works on a Home Assistant instance with no external URL.
"""
from __future__ import annotations

import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import requests

_LOGGER = logging.getLogger(__name__)

API_BASE = "https://api.smartthings.com"
AUTHORIZE_URL = f"{API_BASE}/oauth/authorize"
TOKEN_URL = f"{API_BASE}/oauth/token"

# r: read device state, x: execute commands. Both are required for the LED.
SCOPES = ["r:devices:*", "x:devices:*"]

# SmartThings accepts an http:// redirect URI when the app is registered but
# rejects it at /oauth/authorize with a bare 403 -- no consent screen, no error
# detail. The redirect must be https. This is Home Assistant's own public OAuth
# redirect helper; nothing needs to be listening, because the user copies the
# resulting URL out of the address bar and pastes it back into the config flow.
REDIRECT_URI = "https://my.home-assistant.io/redirect/oauth"

# Refresh this far before actual expiry so a command never races the deadline.
EXPIRY_MARGIN = 300


class OAuthError(Exception):
    """Raised when the OAuth handshake or a refresh fails."""


def create_api_only_app(pat: str) -> dict[str, str]:
    """Register an API_ONLY SmartApp and return its OAuth client credentials.

    The PAT is used only for this call. Once we hold a refresh token the PAT is
    never needed again and may safely expire.
    """
    app_name = f"ha-samsung-ac-led-{secrets.token_hex(4)}"
    payload = {
        "appName": app_name,
        "displayName": "HA Samsung AC LED",
        "description": "Home Assistant control of the Samsung AC display LED",
        "singleInstance": True,
        "appType": "API_ONLY",
        "classifications": ["AUTOMATION"],
        "oauth": {
            "clientName": "HA Samsung AC LED",
            "scope": SCOPES,
            "redirectUris": [REDIRECT_URI],
        },
    }
    resp = requests.post(
        f"{API_BASE}/v1/apps",
        json=payload,
        headers={"Authorization": f"Bearer {pat}", "Content-Type": "application/json"},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise OAuthError(f"could not create SmartApp ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    client_id = data.get("oauthClientId")
    client_secret = data.get("oauthClientSecret")
    if not client_id or not client_secret:
        raise OAuthError("SmartApp created but no OAuth credentials were returned")

    return {
        "app_name": app_name,
        "client_id": client_id,
        "client_secret": client_secret,
    }


def build_authorize_url(client_id: str) -> str:
    """Build the URL the user visits to grant access."""
    return AUTHORIZE_URL + "?" + urlencode(
        {
            "client_id": client_id,
            "scope": " ".join(SCOPES),
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
        }
    )


def exchange_code(client_id: str, client_secret: str, code: str) -> dict[str, Any]:
    """Trade an authorization code for access and refresh tokens."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
        },
        auth=(client_id, client_secret),
        timeout=30,
    )
    if resp.status_code != 200:
        raise OAuthError(f"code exchange failed ({resp.status_code}): {resp.text[:200]}")
    return _normalise(resp.json())


def refresh(client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any]:
    """Exchange a refresh token for a new access token (and a new refresh token).

    SmartThings rotates the refresh token on every use, so the caller must
    persist whatever comes back or the next refresh will fail.
    """
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
        auth=(client_id, client_secret),
        timeout=30,
    )
    if resp.status_code != 200:
        raise OAuthError(f"token refresh failed ({resp.status_code}): {resp.text[:200]}")
    return _normalise(resp.json())


def _normalise(payload: dict[str, Any]) -> dict[str, Any]:
    """Add an absolute expiry so callers do not have to track request time."""
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + int(payload.get("expires_in", 86400)),
    }


def is_expired(expires_at: float) -> bool:
    """True when the access token is at or near its expiry."""
    return time.time() >= (expires_at - EXPIRY_MARGIN)
