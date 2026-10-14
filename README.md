# Absaar Inverter

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5)](https://www.hacs.xyz/docs/faq/custom_repositories/)
[![Validate](https://github.com/Pewidot/absaar_inverter_ha_integration/actions/workflows/validate.yml/badge.svg)](https://github.com/Pewidot/absaar_inverter_ha_integration/actions/workflows/validate.yml)

[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Pewidot&repository=absaar_inverter_ha_integration&category=integration)
[![Add integration](https://my.home-assistant.io/badges/config_flow.svg)](https://my.home-assistant.io/redirect/config_flow/?domain=absaar)

Home Assistant integration for Absaar inverters, with cloud and local connections.

Tested with Home Assistant 2026.10.1.

| | Cloud | Local |
| --- | --- | --- |
| Connection | Absaar EMS / MINI-EMS account | Datalogger connects to Home Assistant |
| Updates | Every 2 minutes | Every 5 seconds by default |
| Account required | Yes | No |
| Internet required | Yes | No |

## Install

1. Install [HACS](https://www.hacs.xyz/docs/use/), click **Add to HACS** above and download **Absaar Inverter**.
2. Restart Home Assistant.
3. Click **Add integration** above, or open **Settings → Devices & services → Add integration → Absaar Inverter**.
4. Choose **Cloud** or **Local**.

Manual installation: copy `custom_components/absaar` into your Home Assistant `custom_components` directory, then follow steps 2–4. Setup is through the UI; YAML configuration is not supported.

**Upgrading from 2.2.1 or earlier:** the integration folder is now `custom_components/absaar`, matching the existing integration domain. After installing the update, remove any leftover `custom_components/absaar_ems` folder and restart. Keep your existing integration entries; their domain and entity unique IDs have not changed.

## Cloud setup

Add your inverter in the Absaar EMS or MINI-EMS app first. In Home Assistant, enter your app **username (not email)** and password. Stations and inverters are discovered automatically.

## Local setup

Local mode has been tested with the **GT800TL**. Other models using the same datalogger protocol are unverified.

1. Reserve IP addresses for Home Assistant and the datalogger in your router.
2. Choose a **TCP listener port** (default **15444**). The datalogger must be able to reach this port on Home Assistant. For container installations, publish the same TCP port or use host networking.
3. Enter the datalogger's web address and web credentials to manage its destination automatically. Set **Home Assistant IP for the datalogger** to the address it can reach; otherwise it is detected automatically.
4. Submit. The inverter serial is learned from the first connection.

For manual configuration, leave the datalogger web address empty and set its destination in its own web interface: **TCP client**, Home Assistant's IP and the chosen listener port.

Local mode redirects the datalogger away from the vendor cloud, so new readings may stop appearing in the EMS app. Automatic destination changes restart the datalogger. Repeated corrections are spaced out, up to one hour apart.

Use **Configure** on the integration entry to update the datalogger address, credentials or query interval later.

## Sensors and energy

- **Both modes:** daily and lifetime energy, AC power/voltage/frequency, and PV string power/voltage/current.
- **Cloud:** AC current, inverter temperature and station totals, where reported by the device.
- **Local:** connection status and combined PV power. Daily energy is calculated from changes in the lifetime counter.

For the Energy dashboard, select the local **Total Energy** sensor or the cloud station's **Total Power Generation** sensor under solar production.

The GT800TL may power down overnight. Live local measurements become unavailable; the lifetime counter retains its last reading. If local data stays unavailable during daylight, check the datalogger destination, IP reservation and TCP port.

[Report an issue](https://github.com/Pewidot/absaar_inverter_ha_integration/issues) with your connection mode, inverter model and relevant logs. Remove credentials, tokens and serial numbers before sharing logs.
