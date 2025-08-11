"""SmartThings API wrapper for Samsung AC LED control."""
import requests
import logging
from typing import Optional, Dict, Any

_LOGGER = logging.getLogger(__name__)


class SmartThingsController:
    """SmartThings API controller for Samsung AC LED."""
    
    def __init__(self, token: str):
        """Initialize the controller."""
        self.token = token
        self.base_url = "https://api.smartthings.com/v1"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def get_devices(self) -> Optional[list]:
        """Get all devices from SmartThings."""
        try:
            response = requests.get(f"{self.base_url}/devices", headers=self.headers)
            response.raise_for_status()
            return response.json().get("items", [])
        except requests.RequestException as e:
            _LOGGER.error("Error getting devices: %s", e)
            return None
    
    def find_ac_device(self) -> Optional[Dict[str, Any]]:
        """Find the Samsung AC device."""
        devices = self.get_devices()
        if not devices:
            return None
        
        # Look for Samsung AC devices
        for device in devices:
            device_type = device.get("type", "").lower()
            manufacturer = device.get("manufacturerName", "").lower()
            name = device.get("name", "").lower()
            
            if ("samsung" in manufacturer or "air" in name or "ac" in name) and \
               ("airconditioner" in device_type or "air conditioner" in name):
                return device
        
        return None
    
    def get_device_status(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of device."""
        try:
            response = requests.get(
                f"{self.base_url}/devices/{device_id}/status",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            _LOGGER.error("Error getting device status: %s", e)
            return None
    
    def get_ac_power_status(self, device_id: str) -> Optional[bool]:
        """Get current AC power status (on/off)."""
        status = self.get_device_status(device_id)
        if not status:
            return None
        
        # Look for power switch capability
        components = status.get("components", {})
        main_component = components.get("main", {})
        
        # Check the main switch capability
        if "switch" in main_component:
            switch_data = main_component["switch"]
            if isinstance(switch_data, dict) and "switch" in switch_data:
                power_status = switch_data["switch"].get("value")
                _LOGGER.debug("AC power status: %s", power_status)
                return power_status == "on"
        
        _LOGGER.warning("Could not determine AC power status for device %s", device_id)
        return None

    def get_led_status(self, device_id: str) -> Optional[str]:
        """Get current LED light status."""
        status = self.get_device_status(device_id)
        if not status:
            return None
        
        # Look for LED-related capabilities
        components = status.get("components", {})
        main_component = components.get("main", {})
        
        # Try Samsung-specific lighting capability first
        if "samsungce.airConditionerLighting" in main_component:
            lighting_data = main_component["samsungce.airConditionerLighting"]
            if isinstance(lighting_data, dict) and "lighting" in lighting_data:
                current_value = lighting_data["lighting"].get("value")
                _LOGGER.debug("Found Samsung AC lighting capability: %s", current_value)
                return current_value
        
        # Fallback to other LED-specific capabilities
        led_capabilities = [
            "indicatorStatus",
            "ledIndicator", 
            "displayLight",
            "panelLight",
            "lightIndicator",
            "statusLight",
            "indicatorLight"
        ]
        
        for capability in led_capabilities:
            if capability in main_component:
                led_status = main_component[capability]
                if isinstance(led_status, dict):
                    return led_status.get("value")
                return led_status
        
        _LOGGER.warning("Could not find LED capability for device %s", device_id)
        return None
    
    def set_led_status(self, device_id: str, state: str) -> bool:
        """Set LED light status (on/off)."""
        
        # Use the command format that works for Samsung AC lighting
        primary_capability = "samsungce.airConditionerLighting"
        
        # Try the working command format first (direct command)
        command_data = {
            "commands": [
                {
                    "component": "main",
                    "capability": primary_capability,
                    "command": state
                }
            ]
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/devices/{device_id}/commands",
                headers=self.headers,
                json=command_data
            )
            
            if response.status_code == 200:
                _LOGGER.debug("Successfully set LED to %s", state)
                return True
            else:
                _LOGGER.error("Failed to set LED: %s - %s", response.status_code, response.text)
                
        except requests.RequestException as e:
            _LOGGER.error("Error setting LED: %s", e)
        
        # Fallback to other command formats if the primary one fails
        alternative_commands = [
            # Try with setLighting command
            {"command": "setLighting", "arguments": [state]},
            # Try with different argument format
            {"command": "setLighting", "arguments": {"lighting": state}},
            # Try direct lighting command
            {"command": "lighting", "arguments": [state]}
        ]
        
        for alt_cmd in alternative_commands:
            command_data = {
                "commands": [
                    {
                        "component": "main", 
                        "capability": primary_capability,
                        **alt_cmd
                    }
                ]
            }
            
            try:
                response = requests.post(
                    f"{self.base_url}/devices/{device_id}/commands",
                    headers=self.headers,
                    json=command_data
                )
                
                if response.status_code == 200:
                    _LOGGER.debug("Successfully set LED to %s using fallback command", state)
                    return True
                    
            except requests.RequestException as e:
                continue
        
        _LOGGER.error("Failed to set LED to %s - all command formats failed", state)
        return False