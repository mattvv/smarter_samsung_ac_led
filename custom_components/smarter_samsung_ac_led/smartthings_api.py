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

        # DEBUG: Log all available capabilities
        _LOGGER.warning("=== DEBUG: All capabilities for device %s ===", device_id)
        _LOGGER.warning("Main component capabilities: %s", list(main_component.keys()))

        # Try Samsung-specific lighting capability first
        if "samsungce.airConditionerLighting" in main_component:
            lighting_data = main_component["samsungce.airConditionerLighting"]
            if isinstance(lighting_data, dict) and "lighting" in lighting_data:
                current_value = lighting_data["lighting"].get("value")
                _LOGGER.debug("Found Samsung AC lighting capability: %s", current_value)
                return current_value

        # NEW: Check for Samsung execute capability with display options
        if "execute" in main_component:
            execute_data = main_component["execute"]
            _LOGGER.warning("Found execute capability: %s", execute_data)

            # For execute capability, we can't determine current state easily
            # since it's a command interface, not a status interface
            # Return "unknown" to indicate we support control but don't know current state
            return "unknown"

        # NEW: Check for custom.doNotDisturbMode (might control display)
        if "custom.doNotDisturbMode" in main_component:
            dnd_data = main_component["custom.doNotDisturbMode"]
            _LOGGER.warning("Found doNotDisturbMode: %s", dnd_data)
            if isinstance(dnd_data, dict):
                # DoNotDisturb might control display - if enabled, display is off
                dnd_value = dnd_data.get("value")
                if dnd_value is not None:
                    # Invert logic: DND on = display off, DND off = display on
                    return "off" if dnd_value else "on"

        # NEW: Check for custom.airConditionerOptionalMode
        if "custom.airConditionerOptionalMode" in main_component:
            optional_mode_data = main_component["custom.airConditionerOptionalMode"]
            _LOGGER.warning("Found airConditionerOptionalMode: %s", optional_mode_data)
            if isinstance(optional_mode_data, dict):
                mode_value = optional_mode_data.get("value")
                # Some optional modes might indicate display state
                if mode_value == "quiet":
                    return "off"  # Quiet mode might mean display is off
                else:
                    return "on"   # Other modes might mean display is on

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

        # Check if device has execute capability - if so, assume it's controllable
        if "execute" in main_component:
            _LOGGER.info("Device %s has execute capability - assuming display is controllable", device_id)
            return "on"  # Default assumption for Samsung ACs with execute capability

        _LOGGER.warning("Could not find LED capability for device %s", device_id)
        return None

    def set_led_status(self, device_id: str, state: str) -> bool:
        """Set LED light status (on/off)."""

        # Get device status to determine which method to use
        device_status = self.get_device_status(device_id)
        if not device_status:
            _LOGGER.error("Could not get device status for %s", device_id)
            return False

        components = device_status.get("components", {})
        main_component = components.get("main", {})

        # Method 1: Try Samsung-specific lighting capability (original method)
        if "samsungce.airConditionerLighting" in main_component:
            _LOGGER.info("Using samsungce.airConditionerLighting for device %s", device_id)
            return self._set_led_via_lighting_capability(device_id, state)

        # Method 2: NEW - Try Samsung execute capability with display options
        if "execute" in main_component:
            _LOGGER.info("Using execute capability for display control on device %s", device_id)
            return self._set_led_via_execute_capability(device_id, state)

        # Method 3: NEW - Try doNotDisturbMode control
        if "custom.doNotDisturbMode" in main_component:
            _LOGGER.info("Using doNotDisturbMode for display control on device %s", device_id)
            return self._set_led_via_dnd_mode(device_id, state)

        # Method 4: NEW - Try airConditionerOptionalMode
        if "custom.airConditionerOptionalMode" in main_component:
            _LOGGER.info("Using airConditionerOptionalMode for display control on device %s", device_id)
            return self._set_led_via_optional_mode(device_id, state)

        # Method 5: Fallback to standard LED capabilities
        return self._set_led_via_standard_capabilities(device_id, state, main_component)

    def _set_led_via_lighting_capability(self, device_id: str, state: str) -> bool:
        """Set LED using samsungce.airConditionerLighting capability (original method)."""
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
                _LOGGER.debug("Successfully set LED to %s via lighting capability", state)
                return True
            else:
                _LOGGER.warning("Primary lighting command failed: %s - %s", response.status_code, response.text)

        except requests.RequestException as e:
            _LOGGER.error("Error setting LED via lighting capability: %s", e)

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
                    _LOGGER.debug("Successfully set LED to %s using fallback lighting command", state)
                    return True

            except requests.RequestException as e:
                continue

        _LOGGER.error("Failed to set LED via lighting capability - all command formats failed")
        return False

    def _set_led_via_execute_capability(self, device_id: str, state: str) -> bool:
        """Set LED using Samsung execute capability with display options."""
        # Samsung display control via execute capability
        light_option = "Light_On" if state == "on" else "Light_Off"

        command_data = {
            "commands": [{
                "component": "main",
                "capability": "execute",
                "command": "execute",
                "arguments": [
                    "mode/vs/0",
                    {
                        "x.com.samsung.da.options": [light_option]
                    }
                ]
            }]
        }

        _LOGGER.warning("Sending Samsung execute display command: %s", command_data)

        try:
            response = requests.post(
                f"{self.base_url}/devices/{device_id}/commands",
                headers=self.headers,
                json=command_data
            )

            if response.status_code == 200:
                _LOGGER.info("Successfully set LED to %s via execute capability", state)
                return True
            else:
                _LOGGER.error("Failed to set LED via execute: %s - %s", response.status_code, response.text)
                return False

        except requests.RequestException as e:
            _LOGGER.error("Error setting LED via execute capability: %s", e)
            return False

    def _set_led_via_dnd_mode(self, device_id: str, state: str) -> bool:
        """Set LED using doNotDisturbMode control."""
        # Invert logic: display on = DND off, display off = DND on
        dnd_state = "off" if state == "on" else "on"

        command_data = {
            "commands": [{
                "component": "main",
                "capability": "custom.doNotDisturbMode",
                "command": "setDoNotDisturb",
                "arguments": [dnd_state]
            }]
        }

        try:
            response = requests.post(
                f"{self.base_url}/devices/{device_id}/commands",
                headers=self.headers,
                json=command_data
            )

            if response.status_code == 200:
                _LOGGER.info("Successfully set LED to %s via doNotDisturbMode", state)
                return True
            else:
                _LOGGER.error("Failed to set LED via DND mode: %s - %s", response.status_code, response.text)
                return False

        except requests.RequestException as e:
            _LOGGER.error("Error setting LED via DND mode: %s", e)
            return False

    def _set_led_via_optional_mode(self, device_id: str, state: str) -> bool:
        """Set LED using airConditionerOptionalMode."""
        # Try using quiet mode to control display
        mode = "quiet" if state == "off" else "normal"

        command_data = {
            "commands": [{
                "component": "main",
                "capability": "custom.airConditionerOptionalMode",
                "command": "setAcOptionalMode",
                "arguments": [mode]
            }]
        }

        try:
            response = requests.post(
                f"{self.base_url}/devices/{device_id}/commands",
                headers=self.headers,
                json=command_data
            )

            if response.status_code == 200:
                _LOGGER.info("Successfully set LED to %s via optional mode", state)
                return True
            else:
                _LOGGER.error("Failed to set LED via optional mode: %s - %s", response.status_code, response.text)
                return False

        except requests.RequestException as e:
            _LOGGER.error("Error setting LED via optional mode: %s", e)
            return False

    def _set_led_via_standard_capabilities(self, device_id: str, state: str, main_component: Dict[str, Any]) -> bool:
        """Set LED using standard LED capabilities as fallback."""
        led_capabilities = [
            ("indicatorStatus", "setIndicatorStatus"),
            ("ledIndicator", "setLedIndicator"),
            ("displayLight", "setDisplayLight"),
            ("panelLight", "setPanelLight"),
            ("lightIndicator", "setLightIndicator"),
            ("statusLight", "setStatusLight"),
            ("indicatorLight", "setIndicatorLight")
        ]

        for capability, command in led_capabilities:
            if capability in main_component:
                command_data = {
                    "commands": [{
                        "component": "main",
                        "capability": capability,
                        "command": command,
                        "arguments": [state]
                    }]
                }

                try:
                    response = requests.post(
                        f"{self.base_url}/devices/{device_id}/commands",
                        headers=self.headers,
                        json=command_data
                    )

                    if response.status_code == 200:
                        _LOGGER.info("Successfully set LED to %s via %s", state, capability)
                        return True

                except requests.RequestException as e:
                    continue

        _LOGGER.error("No supported LED control method found for device %s", device_id)
        return False
