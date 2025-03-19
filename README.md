# absaar_inverter_ha_integration
A simple Absaar Integration for use with the Absaar EMS App
It updates every 2 Minutes (added so you wont get blocked for spamming)
Just write an issue if any information is missing inside HA, nearly everything is accessable.
Does although support Absaar Batteryssystems
Usage:
1. Create if not already done an account in the Absaar EMS App and add your inverter (https://play.google.com/store/apps/details?id=com.hy.miniemse&hl=de or https://apps.apple.com/gb/app/absaarems/id6477900092)
2. Create Folder /homeassistant/custom_components/absaar/ and insert __init__.py & manifest.json & sensor.py
3. edit your configuration.yaml and add the lines from the configuration.yaml of this repository although change the password and username to your absaar ems username(not email) and password
4. save and restart HomeAssistant


Data Exposed:
("acVoltage", "V"),
("acFrequency", "Hz"),
("dcPower", "W"),
("pv1Voltage", "V"),
("pv1Electric", "A"),
("pv1Power", "W"),
("pv2Voltage", "V"),
("pv2Electric", "A"),
("pv2Power", "W"),
("temperature", "°C"),
("batteryVoltage", "V"),
("batteryCurrent", "A"),
("batteryPower", "W"),
("loadPower", "W"),
("controllerTemperature", "°C"),


