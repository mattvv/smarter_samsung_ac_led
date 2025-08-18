# Smarter Samsung AC LED

A Home Assistant integration for controlling the LED display on Samsung SmartThings air conditioners. Turn off that annoying bright LED at night with the click of a button or through automation!

## Why This Integration?

If you own a Samsung AC, you've probably experienced the frustration of that always-on LED display lighting up your room at night. While you can turn it off using the remote, it's buried in menus and resets frequently. This integration creates a standard Home Assistant Light entity that you can easily control and automate.

## Features

- 🔆 **Simple LED Control**: Turn your AC's LED display on/off like any other light
- ⚡ **Smart Power Detection**: Automatically disables LED control when AC is powered off
- 🔄 **Configurable Polling**: Adjust update frequency (5-300 seconds) to balance responsiveness vs API usage
- 🏠 **Full Home Assistant Integration**: Works with automations, scenes, and the UI
- 🛠️ **Easy Setup**: Config flow guides you through device selection

## Installation

### Via HACS (Recommended)

1. Add this repository to HACS as a custom repository:
   - Go to HACS → Integrations → ⋮ → Custom repositories
   - Add: `https://github.com/sfox38/smarter_samsung_ac_led`
   - Category: Integration

2. Install "Smarter Samsung AC LED" from HACS

3. Restart Home Assistant

### Manual Installation

1. Download the latest release
2. Copy the `smarter_samsung_ac_led` folder to your `custom_components` directory
3. Restart Home Assistant

## Setup

1. Go to **Settings** → **Devices & Services** → **+ Add Integration**

2. Search for "Smarter Samsung AC LED"

3. Enter your SmartThings Personal Access Token (PAT).

   ⚠️ **IMPORTANT**: You must use a PAT issued before December 2024, which have an indefinite lifespan. Newer PATs only live for 24 hours, which means this integration would only work for 24 hours.

5. Select your AC device from the list

6. Configure polling interval (optional)
   - Default: 30 seconds
   - Fast updates: 10-15 seconds
   - Power/CPU saving: 60+ seconds

## Usage

Once configured, you'll have a new Light entity for your AC's LED display:

- **Turn On/Off**: Use like any other light in Home Assistant
- **Automations**: Create rules to turn off LED at bedtime
- **Status Monitoring**: Entity shows AC power status and LED state

### Example Automation

```yaml
automation:
  - alias: "Turn off AC LED at bedtime"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: light.turn_off
        target:
          entity_id: light.bedroom_ac_led
```

## Compatibility

This integration has been tested with Samsung WindFree air conditioners but should work with other Samsung SmartThings AC models that support LED control.

**Supported Models:**
- WindFree series (confirmed working)
- Other Samsung SmartThings AC units (likely compatible)

If your device doesn't appear during setup, it may not have the required LED control capability.

## Configuration Options

Access these through **Settings** → **Devices & Services** → **Smarter Samsung AC LED** → **Configure**:

- **Update Interval**: How often to check AC status (5-300 seconds)

## Troubleshooting

### Device Not Found
- Ensure your AC is properly connected to SmartThings
- Verify that your Personal Access Token (PAT) has the correct permissions and has not expired
- Check that your AC model supports LED control

### LED Control Not Working
- Make sure your AC is powered on (LED control only works when AC is running)
- Try adjusting the polling interval for faster updates
- Check Home Assistant logs for API errors

## Development Notes

This integration was developed to fill a gap in the official SmartThings integration, which doesn't currently support AC LED control. It uses the SmartThings API to monitor AC power status and control the LED display capability.

The integration will become redundant if/when the official SmartThings integration adds LED support, but will continue to work alongside it.

This integration was developed with the support of claude.ai.

## Contributing

Issues and pull requests are welcome! This project was created to solve a specific need, but community contributions can help make it work for more devices and use cases.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

---

**Note**: This integration requires a SmartThings Personal Access Token and internet connectivity to function. LED control is only available when your AC is powered on.
