"""SmartThings API wrapper for Samsung AC LED control.

Authentication is OAuth: the controller holds a refresh token and mints access
tokens as needed. See oauth.py for why a Personal Access Token cannot be used.

LED control goes through the `execute` capability. Samsung does not expose
`samsungce.airConditionerLighting` on these units, and `execute` is a
command-only interface -- it reports no state -- so the light entity is
optimistic (assumed_state).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import requests

from . import oauth

_LOGGER = logging.getLogger(__name__)

API_BASE = "https://api.smartthings.com/v1"

# The payload Samsung's own app sends to toggle the front-panel display.
#
# NOTE: these option names are INVERTED on this hardware. Verified by hand on a
# Samsung ARTIK051_PRAC_20K (2026-09-16): sending "Light_Off" leaves the display
# lit, sending "Light_On" turns it dark. Do not "fix" this mapping without
# re-testing against a real unit with the AC powered on -- the display shows
# nothing at all while the AC is off, which makes it easy to mis-read.
LED_OPTION = {True: "Light_Off", False: "Light_On"}


class AuthFailed(Exception):
    """Credentials are no longer usable and the user must re-authenticate."""


class SmartThingsController:
    """Talks to SmartThings on behalf of one Samsung AC."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        access_token: str | None = None,
        expires_at: float = 0.0,
        token_saver: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token = access_token
        self._expires_at = expires_at
        self._token_saver = token_saver

    # ------------------------------------------------------------------ auth

    def _valid_access_token(self) -> str:
        """Return a usable access token, refreshing first if necessary."""
        if self._access_token and not oauth.is_expired(self._expires_at):
            return self._access_token

        try:
            tokens = oauth.refresh(self._client_id, self._client_secret, self._refresh_token)
        except oauth.OAuthError as err:
            raise AuthFailed(str(err)) from err

        self._access_token = tokens["access_token"]
        self._expires_at = tokens["expires_at"]
        # SmartThings rotates the refresh token, so persist the new one or the
        # next refresh will fail with an invalid_grant.
        if tokens.get("refresh_token"):
            self._refresh_token = tokens["refresh_token"]
        if self._token_saver:
            self._token_saver(
                {
                    "access_token": self._access_token,
                    "refresh_token": self._refresh_token,
                    "expires_at": self._expires_at,
                }
            )
        _LOGGER.debug("Refreshed SmartThings access token")
        return self._access_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._valid_access_token()}",
            "Content-Type": "application/json",
        }

    # ----------------------------------------------------------------- calls

    def get_devices(self) -> list[dict[str, Any]]:
        """Return every device on the account."""
        resp = requests.get(f"{API_BASE}/devices", headers=self._headers(), timeout=30)
        if resp.status_code == 401:
            raise AuthFailed("SmartThings rejected the access token")
        resp.raise_for_status()
        return resp.json().get("items", [])

    def get_ac_devices(self) -> list[dict[str, Any]]:
        """Return devices that expose the `execute` capability on `main`.

        That capability is what carries the LED command, so its presence is the
        only meaningful compatibility test.
        """
        compatible = []
        for device in self.get_devices():
            for component in device.get("components", []):
                if component.get("id") != "main":
                    continue
                caps = {c.get("id") for c in component.get("capabilities", [])}
                if "execute" in caps and "airConditionerMode" in caps:
                    compatible.append(device)
                break
        return compatible

    def get_ac_power_status(self, device_id: str) -> bool | None:
        """Return True when the AC itself is running, None when unknown."""
        resp = requests.get(
            f"{API_BASE}/devices/{device_id}/status", headers=self._headers(), timeout=30
        )
        if resp.status_code == 401:
            raise AuthFailed("SmartThings rejected the access token")
        if resp.status_code != 200:
            return None
        switch = resp.json().get("components", {}).get("main", {}).get("switch", {})
        value = switch.get("switch", {}).get("value")
        return None if value is None else value == "on"

    def set_led_status(self, device_id: str, on: bool) -> bool:
        """Turn the front-panel LED on or off. Returns True on success."""
        body = {
            "commands": [
                {
                    "component": "main",
                    "capability": "execute",
                    "command": "execute",
                    "arguments": [
                        "mode/vs/0",
                        {"x.com.samsung.da.options": [LED_OPTION[bool(on)]]},
                    ],
                }
            ]
        }
        resp = requests.post(
            f"{API_BASE}/devices/{device_id}/commands",
            json=body,
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code == 401:
            raise AuthFailed("SmartThings rejected the access token")
        if resp.status_code != 200:
            _LOGGER.error("LED command failed (%s): %s", resp.status_code, resp.text[:200])
            return False

        results = resp.json().get("results", [])
        ok = all(r.get("status") in ("COMPLETED", "ACCEPTED") for r in results)
        if not ok:
            _LOGGER.error("LED command was not accepted: %s", results)
        return ok
