"""Light platform for Samsung AC LED Controller integration."""
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.light import LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.const import STATE_ON, STATE_OFF

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, CONF_SCAN_INTERVAL
from .smartthings_api import SmartThingsController

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Samsung AC LED light platform."""
    
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    device_id = hass.data[DOMAIN][config_entry.entry_id]["device_id"]
    device_name = config_entry.data.get("device_name", "Samsung AC")
    
    # Get scan interval from options
    scan_interval = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    
    # Create data update coordinator
    coordinator = SamsungACLEDCoordinator(hass, controller, device_id, scan_interval)
    
    # Store coordinator for options updates
    hass.data[DOMAIN][config_entry.entry_id]["coordinator"] = coordinator
    
    # Fetch initial data so we have data when entities subscribe
    await coordinator.async_config_entry_first_refresh()
    
    # Add the light entity
    async_add_entities([SamsungACLEDLight(coordinator, device_name)], True)


class SamsungACLEDCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Samsung AC LED data."""
    
    def __init__(
        self,
        hass: HomeAssistant,
        controller: SmartThingsController,
        device_id: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize."""
        self.controller = controller
        self.device_id = device_id
        self._last_ac_power_state = None
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
    
    def update_scan_interval(self, scan_interval: int) -> None:
        """Update the scan interval."""
        self.update_interval = timedelta(seconds=scan_interval)
        _LOGGER.debug("Updated scan interval to %s seconds", scan_interval)
    
    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""
        try:
            # Get both LED status and AC power status
            ac_power_status = await self.hass.async_add_executor_job(
                self.controller.get_ac_power_status, self.device_id
            )
            
            # Check if AC power state changed
            ac_power_changed = self._last_ac_power_state != ac_power_status
            self._last_ac_power_state = ac_power_status
            
            # Only get LED status if AC is on or if we need to check initial state
            led_status = None
            if ac_power_status or self.data is None:
                led_status = await self.hass.async_add_executor_job(
                    self.controller.get_led_status, self.device_id
                )
            else:
                # AC is off, so LED is definitely off
                led_status = "off"
            
            if led_status is None and ac_power_status:
                raise UpdateFailed("Failed to get LED status")
            
            data = {
                "led_status": led_status,
                "ac_power_on": ac_power_status,
                "ac_power_changed": ac_power_changed
            }
            
            # Log power state changes for debugging
            if ac_power_changed:
                _LOGGER.info("AC power state changed to: %s", ac_power_status)
            
            return data
            
        except Exception as exception:
            raise UpdateFailed(f"Error communicating with API: {exception}") from exception

    def force_refresh(self):
        """Force an immediate refresh of the coordinator data."""
        self.hass.async_create_task(self.async_request_refresh())


class SamsungACLEDLight(CoordinatorEntity, LightEntity):
    """Samsung AC LED light entity."""
    
    def __init__(
        self,
        coordinator: SamsungACLEDCoordinator,
        device_name: str,
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator)
        self.device_name = device_name
        
        # Create a cleaner entity name - remove manufacturer info and just use "Air Conditioner LED"
        clean_name = device_name
        # Remove common manufacturer prefixes
        prefixes_to_remove = ["Samsung-Room-", "Samsung ", "Samsung-"]
        for prefix in prefixes_to_remove:
            if clean_name.startswith(prefix):
                clean_name = clean_name[len(prefix):]
                break
        
        # If it still has technical terms, simplify to "Air Conditioner"
        if any(term in clean_name.lower() for term in ["air-conditioner", "airconditioner"]):
            clean_name = "Air Conditioner"
        
        # Entity attributes
        self._attr_name = f"{clean_name} LED"
        self._attr_unique_id = f"{coordinator.device_id}_led"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:led-outline"
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Check if AC power state changed and force immediate update
        if self.coordinator.data and self.coordinator.data.get("ac_power_changed"):
            _LOGGER.debug("AC power state changed, forcing immediate LED update")
        
        super()._handle_coordinator_update()
        
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.device_id)},
            "name": self.device_name,
            "manufacturer": "Samsung",
            "model": "SmartThings AC",
            "via_device": (DOMAIN, self.coordinator.device_id),
        }
    
    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        if self.coordinator.data is None:
            return None
        
        # If AC is powered off, LED is definitely off regardless of stored LED status
        ac_power_on = self.coordinator.data.get("ac_power_on", False)
        if not ac_power_on:
            return False
        
        # If AC is on, return the actual LED status
        led_status = self.coordinator.data.get("led_status")
        return led_status == "on"
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False
        
        # Entity is only available if AC is powered on
        if self.coordinator.data is None:
            return False
        
        return self.coordinator.data.get("ac_power_on", False)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if self.coordinator.data is None:
            return {}
        
        ac_power_on = self.coordinator.data.get("ac_power_on", False)
        scan_interval = self.coordinator.update_interval.total_seconds() if self.coordinator.update_interval else DEFAULT_SCAN_INTERVAL
        
        attributes = {
            "ac_power_status": "on" if ac_power_on else "off",
            "scan_interval": int(scan_interval)
        }
        
        # Only show LED status if AC is powered on
        if ac_power_on:
            led_status = self.coordinator.data.get("led_status", "unknown")
            attributes["led_status"] = led_status
        else:
            attributes["led_status"] = "unavailable (AC off)"
        
        return attributes
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        # Check if AC is powered on before allowing LED control
        if not self.available:
            _LOGGER.warning("Cannot control LED - AC is not powered on")
            return
        
        success = await self.hass.async_add_executor_job(
            self.coordinator.controller.set_led_status,
            self.coordinator.device_id,
            "on"
        )
        
        if success:
            # Update coordinator data immediately to reflect change
            current_data = self.coordinator.data or {}
            current_data["led_status"] = "on"
            self.coordinator.async_set_updated_data(current_data)
        else:
            _LOGGER.error("Failed to turn on LED")
    
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        # Check if AC is powered on before allowing LED control
        if not self.available:
            _LOGGER.warning("Cannot control LED - AC is not powered on")
            return
        
        success = await self.hass.async_add_executor_job(
            self.coordinator.controller.set_led_status,
            self.coordinator.device_id,
            "off"
        )
        
        if success:
            # Update coordinator data immediately to reflect change
            current_data = self.coordinator.data or {}
            current_data["led_status"] = "off"
            self.coordinator.async_set_updated_data(current_data)
        else:
            _LOGGER.error("Failed to turn off LED")