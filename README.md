# Absaar Inverter Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

A Home Assistant integration for Absaar EMS inverters and battery systems. Since version 2.0.0 you can choose per entry how Home Assistant connects to your inverter:

- **Cloud**: through the Absaar EMS cloud service (MINI-EMS is also supported), using your app account.
- **Local**: completely cloud-free — the inverter's WiFi datalogger connects directly to Home Assistant, which decodes the data itself. No account, no internet dependency, no stale cloud data.

Existing installations keep working unchanged after upgrading: entries created before 2.0.0 continue as cloud connections. The choice appears when adding a new entry.

## Features

- **GUI Configuration**: Easy setup through Home Assistant's UI
- **Cloud or Local**: Pick per entry — vendor cloud account or direct local connection
- **Automatic Updates**: Cloud mode polls every 2 minutes; local mode receives pushed data every few seconds
- **Comprehensive Data**: Exposes all available inverter metrics
- **Battery Support**: Full support for Absaar battery systems (cloud mode)
- **Device Registry**: Properly registers devices in Home Assistant
- **Proper Entity IDs**: Uses unique identifiers for all sensors

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/Pewidot/absaar_inverter_ha_integration`
6. Select category "Integration"
7. Click "Add"
8. Search for "Absaar Inverter" in HACS
9. Click "Download"
10. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/absaar_ems` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

### Prerequisites

Before configuring the integration, you need:
1. An account in the Absaar EMS App with your inverter added
   - [Android App](https://play.google.com/store/apps/details?id=com.hy.miniemse&hl=de)
   - [iOS App](https://apps.apple.com/gb/app/absaarems/id6477900092)
2. Your Absaar EMS username (not email) and password

### Setup via UI

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for **Absaar Inverter**
4. Choose **Cloud** or **Local**

#### Cloud mode

Enter your Absaar EMS username and password and click **Submit**. The integration will automatically discover your stations and inverters and create all sensors.

#### Local mode (cloud-free)

In local mode the inverter's WiFi datalogger connects directly to Home Assistant on a TCP port (default 15444, the same port it normally uses toward the vendor cloud). The integration decodes the data itself — the Absaar servers are never contacted.

For this to work the datalogger must be pointed at your Home Assistant IP. There are two ways:

- **Automatic (recommended)**: enter the datalogger's web address (e.g. `http://192.168.1.50`) and its web login (default `admin`/`admin`) in the setup form. The integration checks periodically that the datalogger targets Home Assistant and corrects it if the app or a reset changed it.
- **Manual**: open the datalogger's web interface yourself and set the TCP client destination to your Home Assistant IP and the chosen port, then leave the web address field empty.

All other fields have sensible defaults. The inverter serial is auto-detected from the first connection.

Notes on local mode:
- The inverter is unpowered at night, so its sensors show *unavailable* until sunrise. The lifetime total keeps its last value, and the Energy Dashboard derives daily production from it — no daily counter from the cloud is needed (which also avoids the cloud's stale morning values).
- **Give the datalogger a static DHCP reservation in your router.** Its IP changes on reboot otherwise, and the automatic IP-keeper then can't reach it anymore. If it does change, use **Configure** on the integration entry to update the datalogger web address — no need to remove and re-add the entry.
- Entities are anchored to the inverter's serial number once it has connected, so even a re-created entry reuses the same entities and keeps their long-term statistics.
- Local mode has been tested with the GT800TL. Other models using the same datalogger protocol may work; battery-system metrics are currently cloud-only.
- Cloud and local entries can exist side by side if you want to compare.

### Legacy YAML Configuration (Deprecated)

The old YAML configuration method is no longer supported. Please use the UI configuration method above. If you have an existing YAML configuration, remove it from your `configuration.yaml` and reconfigure through the UI.


## Available Sensors

### Local Mode Sensors

- **Total Energy** (kWh) — lifetime generation (use this in the Energy Dashboard)
- **Daily Energy** (kWh) — today's production, derived locally from the lifetime total; resets at local midnight and survives restarts
- **AC Power / Voltage / Frequency** — current output
- **PV1/PV2 Power, Voltage, Current** and **PV Total Power** — per-string DC input
- **Status** — online/offline, with serial and last-seen time as attributes

### Cloud Mode Sensors

The integration creates the following sensors for each inverter/station:

#### Station Sensors
- **Daily Power Generation** (kWh) - Total energy generated today
- **Total Power Generation** (kWh) - Lifetime energy generation

#### Inverter Sensors
- **AC Power** (W) - Current AC output power
- **AC Voltage** (V) - AC output voltage
- **AC Frequency** (Hz) - AC frequency
- **AC Current** (A) - AC output current
- **PV1 Power** (W) - Solar panel string 1 power
- **PV1 Voltage** (V) - Solar panel string 1 voltage
- **PV1 Current** (A) - Solar panel string 1 current
- **PV2 Power** (W) - Solar panel string 2 power
- **PV2 Voltage** (V) - Solar panel string 2 voltage
- **PV2 Current** (A) - Solar panel string 2 current
- **Input Power** (W) - Total DC input power
- **Temperature** (°C) - Inverter temperature

Additional sensors may be available depending on your specific hardware configuration, including:
- Battery voltage, current, and power
- Load power
- Controller temperature

## Troubleshooting

### Integration not showing up

1. Make sure you've restarted Home Assistant after installation
2. Check the logs for any errors: **Settings** → **System** → **Logs**
3. Verify that the `custom_components/absaar_ems` folder is in the correct location

### Authentication fails

1. Verify your username (not email address) and password are correct
2. Try logging into the Absaar EMS mobile app to confirm your credentials
3. Check your internet connection
4. The API endpoint may be temporarily unavailable - try again later

### No data showing

1. Check that your inverter is online and communicating with the Absaar EMS cloud
2. Verify in the mobile app that data is being received
3. Check Home Assistant logs for any API errors

## Support

If you encounter any issues or have feature requests, please:
1. Check existing [issues](https://github.com/Pewidot/absaar_inverter_ha_integration/issues)
2. Create a new issue with detailed information about your problem

## Contributing

Contributions are welcome! Please feel free to submit pull requests or create issues for bugs and feature requests.

## Credits

- Created by [@Pewidot](https://github.com/Pewidot)
- Refactored with modern Home Assistant best practices

## License

This project is provided as-is for use with Absaar EMS systems.


