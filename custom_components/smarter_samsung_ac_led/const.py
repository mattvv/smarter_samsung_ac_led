"""Constants for the Samsung AC LED Controller integration."""

DOMAIN = "smarter_samsung_ac_led"

# Configuration keys
CONF_TOKEN = "token"
CONF_DEVICE_ID = "device_id"
CONF_SCAN_INTERVAL = "scan_interval"

# Default values
DEFAULT_NAME = "Smarter Samsung AC LED"
DEFAULT_SCAN_INTERVAL = 10  # seconds

# Scan interval limits
MIN_SCAN_INTERVAL = 5   # seconds
MAX_SCAN_INTERVAL = 300 # seconds