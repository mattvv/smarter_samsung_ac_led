"""Samsung AC LED Controller integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DEVICE_ID,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from .smartthings_api import AuthFailed, SmartThingsController

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Samsung AC LED Controller from a config entry."""

    def _save_tokens(tokens: dict) -> None:
        """Persist rotated OAuth tokens back onto the config entry.

        SmartThings issues a new refresh token on every refresh and invalidates
        the old one, so failing to store this would break the integration on the
        following refresh.
        """
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: tokens["access_token"],
                CONF_REFRESH_TOKEN: tokens["refresh_token"],
                CONF_EXPIRES_AT: tokens["expires_at"],
            },
        )

    controller = SmartThingsController(
        client_id=entry.data[CONF_CLIENT_ID],
        client_secret=entry.data[CONF_CLIENT_SECRET],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        access_token=entry.data.get(CONF_ACCESS_TOKEN),
        expires_at=entry.data.get(CONF_EXPIRES_AT, 0.0),
        token_saver=_save_tokens,
    )

    # Fail fast with a re-auth prompt rather than leaving dead entities around.
    try:
        await hass.async_add_executor_job(
            controller.get_ac_power_status, entry.data[CONF_DEVICE_ID]
        )
    except AuthFailed as err:
        raise ConfigEntryAuthFailed(str(err)) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "controller": controller,
        "device_id": entry.data[CONF_DEVICE_ID],
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
