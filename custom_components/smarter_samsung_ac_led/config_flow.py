"""Config flow for Samsung AC LED Controller integration."""
import logging
import voluptuous as vol
from typing import Any, Dict, Optional

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store

from .const import DOMAIN, CONF_TOKEN, CONF_DEVICE_ID, DEFAULT_SCAN_INTERVAL
from .smartthings_api import SmartThingsController

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_tokens"

# Configuration constants
CONF_SCAN_INTERVAL = "scan_interval"
MIN_SCAN_INTERVAL = 5  # seconds
MAX_SCAN_INTERVAL = 300  # seconds


def get_token_schema(default_token: str = "") -> vol.Schema:
    """Get the token input schema with optional default token."""
    return vol.Schema({
        vol.Required("token", default=default_token): str,
    })


def get_device_selection_schema(devices: Dict[str, str]) -> vol.Schema:
    """Get the device selection schema."""
    return vol.Schema({
        vol.Required("device_selection"): vol.In(devices),
    })


def get_options_schema(current_interval: int = DEFAULT_SCAN_INTERVAL) -> vol.Schema:
    """Get the options schema."""
    return vol.Schema({
        vol.Optional(
            CONF_SCAN_INTERVAL,
            default=current_interval
        ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
    })


async def validate_token(hass: HomeAssistant, token: str) -> list[dict]:
    """Validate the token and return list of compatible devices."""
    
    controller = SmartThingsController(token)
    
    # Test the connection by getting devices
    devices = await hass.async_add_executor_job(controller.get_devices)
    if not devices:
        raise CannotConnect
    
    # Filter devices that have LED capability
    compatible_devices = []
    for device in devices:
        device_id = device.get("deviceId")
        if not device_id:
            continue
            
        # Check if device has LED capability
        led_status = await hass.async_add_executor_job(controller.get_led_status, device_id)
        if led_status is not None:
            compatible_devices.append(device)
    
    if not compatible_devices:
        raise NoCompatibleDevices
    
    return compatible_devices


async def validate_device_selection(hass: HomeAssistant, token: str, device_id: str, device_name: str) -> dict[str, Any]:
    """Validate the selected device."""
    
    controller = SmartThingsController(token)
    
    # Test LED capability one more time
    led_status = await hass.async_add_executor_job(controller.get_led_status, device_id)
    if led_status is None:
        raise NoLEDCapability
    
    # Return info that you want to store in the config entry.
    return {
        "title": f"{device_name} LED",
        "device_id": device_id,
        "device_name": device_name
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Samsung AC LED Controller."""

    VERSION = 1

    def __init__(self):
        """Initialize config flow."""
        self.token = None
        self.compatible_devices = []

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step - token input."""
        
        # Load previously saved token if available
        stored_data = {}
        if self.hass:
            store = Store(self.hass, STORAGE_VERSION, STORAGE_KEY)
            stored_data = await store.async_load() or {}
        
        default_token = stored_data.get("last_used_token", "")
        
        if user_input is None:
            return self.async_show_form(
                step_id="user", 
                data_schema=get_token_schema(default_token),
                description_placeholders={
                    "setup_url": "https://account.smartthings.com/tokens"
                }
            )

        errors = {}

        try:
            # Validate token and get compatible devices
            self.compatible_devices = await validate_token(self.hass, user_input["token"])
            self.token = user_input["token"]
            
            # Save the token for future use
            if self.hass:
                store = Store(self.hass, STORAGE_VERSION, STORAGE_KEY)
                await store.async_save({"last_used_token": user_input["token"]})
                
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except NoCompatibleDevices:
            errors["base"] = "no_compatible_devices"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            # Move to device selection step
            return await self.async_step_device_selection()

        return self.async_show_form(
            step_id="user", 
            data_schema=get_token_schema(user_input.get("token", default_token)), 
            errors=errors,
            description_placeholders={
                "setup_url": "https://account.smartthings.com/tokens"
            }
        )

    async def async_step_device_selection(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the device selection step."""
        
        if user_input is None:
            # Create device options for dropdown
            device_options = {}
            for device in self.compatible_devices:
                device_id = device.get("deviceId")
                device_name = device.get("name", f"Unknown Device {device_id[:8]}")
                device_label = device.get("label", device_name)  # Use label if available, fallback to name
                room_name = device.get("roomName", "")
                
                # Use the user-defined name, optionally with room info
                if room_name and room_name.lower() not in device_label.lower():
                    display_name = f"{device_label} ({room_name})"
                else:
                    display_name = device_label
                
                device_options[device_id] = display_name
            
            return self.async_show_form(
                step_id="device_selection",
                data_schema=get_device_selection_schema(device_options),
                description_placeholders={
                    "device_count": str(len(device_options))
                }
            )

        # Process device selection
        selected_device_id = user_input["device_selection"]
        
        # Find the selected device
        selected_device = None
        for device in self.compatible_devices:
            if device.get("deviceId") == selected_device_id:
                selected_device = device
                break
        
        if not selected_device:
            return self.async_show_form(
                step_id="device_selection",
                data_schema=get_device_selection_schema({selected_device_id: "Selected Device"}),
                errors={"device_selection": "device_not_found"}
            )

        errors = {}
        try:
            device_name = selected_device.get("name", "Samsung AC")
            info = await validate_device_selection(
                self.hass, 
                self.token, 
                selected_device_id, 
                device_name
            )
                
        except NoLEDCapability:
            errors["base"] = "no_led_capability"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            # Check if already configured
            await self.async_set_unique_id(selected_device_id)
            self._abort_if_unique_id_configured()
            
            # Create the config entry with default options
            return self.async_create_entry(
                title=info["title"], 
                data={
                    "token": self.token,
                    "device_id": info["device_id"],
                    "device_name": info["device_name"]
                },
                options={
                    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL
                }
            )

        # Show device selection form again with errors
        device_options = {}
        for device in self.compatible_devices:
            device_id = device.get("deviceId")
            device_name = device.get("name", f"Unknown Device {device_id[:8]}")
            device_label = device.get("label", device_name)  # Use label if available, fallback to name
            room_name = device.get("roomName", "")
            
            # Use the user-defined name, optionally with room info
            if room_name and room_name.lower() not in device_label.lower():
                display_name = f"{device_label} ({room_name})"
            else:
                display_name = device_label
            
            device_options[device_id] = display_name

        return self.async_show_form(
            step_id="device_selection",
            data_schema=get_device_selection_schema(device_options),
            errors=errors,
            description_placeholders={
                "device_count": str(len(device_options))
            }
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Samsung AC LED Controller."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current scan interval from options or use default
        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=get_options_schema(current_interval),
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class NoACFound(Exception):
    """Error to indicate no Samsung AC was found."""


class InvalidDeviceId(Exception):
    """Error to indicate the device ID is invalid."""


class NoLEDCapability(Exception):
    """Error to indicate the device doesn't have LED capability."""


class NoCompatibleDevices(Exception):
    """Error to indicate no compatible devices were found."""