"""Light entity for the Samsung AC front-panel display LED."""
from __future__ import annotations

import logging

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN
from .smartthings_api import AuthFailed, SmartThingsController

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the LED light from a config entry."""
    stored = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            SamsungACLed(
                controller=stored["controller"],
                device_id=stored["device_id"],
                device_name=entry.data.get(CONF_DEVICE_NAME, "Samsung AC"),
                entry_id=entry.entry_id,
            )
        ]
    )


class SamsungACLed(LightEntity):
    """The AC's display LED.

    SmartThings exposes this only through the write-only `execute` capability,
    so there is no way to read the real state back. The entity is therefore
    optimistic: it reports whatever we last asked for, and Home Assistant shows
    separate on/off controls rather than a toggle.
    """

    _attr_has_entity_name = True
    _attr_name = "Display LED"
    _attr_assumed_state = True
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self,
        controller: SmartThingsController,
        device_id: str,
        device_name: str,
        entry_id: str,
    ) -> None:
        self._controller = controller
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_display_led"
        self._attr_is_on: bool | None = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Samsung",
            model="Air Conditioner",
        )

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the display LED on."""
        await self._send(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the display LED off."""
        await self._send(False)

    async def _send(self, on: bool) -> None:
        try:
            ok = await self.hass.async_add_executor_job(
                self._controller.set_led_status, self._device_id, on
            )
        except AuthFailed as err:
            raise ConfigEntryAuthFailed(str(err)) from err

        if not ok:
            raise HomeAssistantError(
                f"SmartThings did not accept the display LED command for {self._device_id}"
            )

        # Only claim the new state once the command was accepted.
        self._attr_is_on = on
        self.async_write_ha_state()
