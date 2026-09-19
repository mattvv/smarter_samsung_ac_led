"""Config flow for Samsung AC LED Controller.

Setup is four steps:

  1. paste a SmartThings Personal Access Token
  2. we register an API_ONLY SmartApp with it and show an authorize link
  3. you approve, land on a dead localhost URL, and paste that URL back
  4. pick which air conditioner to control

The PAT is used only in step 2 and is never stored. From then on the
integration runs on an OAuth refresh token, which is what makes it survive
SmartThings' 24-hour PAT expiry.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from . import oauth
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_APP_NAME,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from .smartthings_api import SmartThingsController

_LOGGER = logging.getLogger(__name__)

UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the setup handshake."""

    VERSION = 2

    def __init__(self) -> None:
        self._app: dict[str, str] = {}
        self._tokens: dict[str, Any] = {}
        self._devices: list[dict[str, Any]] = []
        self._reauth_entry: config_entries.ConfigEntry | None = None

    # ------------------------------------------------------------- step 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Collect a Personal Access Token and register the SmartApp."""
        errors: dict[str, str] = {}

        if user_input is not None:
            pat = user_input["pat"].strip()
            if not UUID_RE.match(pat):
                errors["pat"] = "invalid_token_format"
            else:
                try:
                    self._app = await self.hass.async_add_executor_job(
                        oauth.create_api_only_app, pat
                    )
                except oauth.OAuthError as err:
                    _LOGGER.error("SmartApp registration failed: %s", err)
                    errors["base"] = "cannot_create_app"
                else:
                    return await self.async_step_authorize()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("pat"): str}),
            errors=errors,
            description_placeholders={"tokens_url": "https://account.smartthings.com/tokens"},
        )

    # ------------------------------------------------------------- step 2/3

    async def async_step_authorize(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show the authorize link, then accept the pasted redirect URL."""
        errors: dict[str, str] = {}
        authorize_url = oauth.build_authorize_url(self._app["client_id"])

        if user_input is not None:
            code = _extract_code(user_input["redirect_url"])
            if not code:
                errors["redirect_url"] = "no_code_found"
            else:
                try:
                    self._tokens = await self.hass.async_add_executor_job(
                        oauth.exchange_code,
                        self._app["client_id"],
                        self._app["client_secret"],
                        code,
                    )
                except oauth.OAuthError as err:
                    _LOGGER.error("Code exchange failed: %s", err)
                    errors["base"] = "exchange_failed"
                else:
                    if self._reauth_entry is not None:
                        return self.async_update_reload_and_abort(
                            self._reauth_entry,
                            data={
                                **self._reauth_entry.data,
                                CONF_REFRESH_TOKEN: self._tokens["refresh_token"],
                                CONF_ACCESS_TOKEN: self._tokens["access_token"],
                                CONF_EXPIRES_AT: self._tokens["expires_at"],
                            },
                        )
                    return await self.async_step_pick_device()

        return self.async_show_form(
            step_id="authorize",
            data_schema=vol.Schema({vol.Required("redirect_url"): str}),
            errors=errors,
            description_placeholders={"authorize_url": authorize_url},
        )

    # ------------------------------------------------------------- reauth

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Re-run the authorize step when the stored refresh token has died.

        The SmartApp registered at setup is still valid, so no PAT is needed --
        only a fresh approval to mint a new refresh token for the same entry.
        """
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._app = {
            "client_id": entry_data[CONF_CLIENT_ID],
            "client_secret": entry_data[CONF_CLIENT_SECRET],
        }
        return await self.async_step_authorize()

    # ------------------------------------------------------------- step 4

    async def async_step_pick_device(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Choose which air conditioner this entry controls."""
        errors: dict[str, str] = {}
        controller = self._controller()

        if not self._devices:
            try:
                self._devices = await self.hass.async_add_executor_job(
                    controller.get_ac_devices
                )
            except Exception as err:  # noqa: BLE001 - surfaced to the user
                _LOGGER.error("Could not list devices: %s", err)
                return self.async_abort(reason="cannot_connect")
            if not self._devices:
                return self.async_abort(reason="no_compatible_devices")

        choices = {
            d["deviceId"]: (d.get("label") or d.get("name") or d["deviceId"])
            for d in self._devices
        }

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()
            name = choices[device_id]
            return self.async_create_entry(
                title=f"{name} LED",
                data={
                    CONF_CLIENT_ID: self._app["client_id"],
                    CONF_CLIENT_SECRET: self._app["client_secret"],
                    CONF_APP_NAME: self._app["app_name"],
                    CONF_REFRESH_TOKEN: self._tokens["refresh_token"],
                    CONF_ACCESS_TOKEN: self._tokens["access_token"],
                    CONF_EXPIRES_AT: self._tokens["expires_at"],
                    CONF_DEVICE_ID: device_id,
                    CONF_DEVICE_NAME: name,
                },
            )

        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID): vol.In(choices)}),
            errors=errors,
        )

    def _controller(self) -> SmartThingsController:
        return SmartThingsController(
            client_id=self._app["client_id"],
            client_secret=self._app["client_secret"],
            refresh_token=self._tokens["refresh_token"],
            access_token=self._tokens["access_token"],
            expires_at=self._tokens["expires_at"],
        )


def _extract_code(pasted: str) -> str | None:
    """Pull the ?code= value out of a pasted redirect URL.

    Accepts a bare code too, since people often copy just that.
    """
    pasted = pasted.strip()
    if "?" not in pasted and "=" not in pasted:
        return pasted or None
    query = parse_qs(urlparse(pasted).query)
    values = query.get("code")
    return values[0] if values else None
