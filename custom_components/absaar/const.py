"""Constants for the Absaar Inverter integration."""

DOMAIN = "absaar"
BASE_URL = "https://mini-ems.com:8081"

# Connection types selectable in the config flow. Legacy config entries
# (created before 2.0.0) have no connection_type key and are treated as cloud.
CONF_CONNECTION_TYPE = "connection_type"
CONNECTION_TYPE_CLOUD = "cloud"
CONNECTION_TYPE_LOCAL = "local"

# Local mode configuration keys
CONF_SERIAL = "serial"
CONF_POLL_DELAY = "poll_delay"
CONF_DATALOGGER_URL = "datalogger_url"
CONF_DATALOGGER_USERNAME = "datalogger_username"
CONF_DATALOGGER_PASSWORD = "datalogger_password"
CONF_LISTENER_IP = "listener_ip"
CONF_IP_CHECK_INTERVAL = "ip_check_interval"

# 15444 is the port the GT800TL datalogger uses toward the vendor cloud, so
# reusing it means only the destination IP has to change on the datalogger.
DEFAULT_PORT = 15444
DEFAULT_POLL_DELAY = 5
DEFAULT_IP_CHECK_INTERVAL = 300
DEFAULT_DATALOGGER_USERNAME = "admin"
DEFAULT_DATALOGGER_PASSWORD = "admin"
