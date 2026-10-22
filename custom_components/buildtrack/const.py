"""Constants for the Buildtrack integration."""

DOMAIN = "buildtrack"

# API Endpoints
# Use HTTPS everywhere: credentials and the session token are passed to these
# endpoints, so they must not travel over plain HTTP. ezcentral.buildtrack.in
# serves a valid certificate (the web UI and the account-info endpoint already
# use HTTPS), so this is safe.
API_BASE_URL = "https://ezcentral.buildtrack.in/btadmin/index.php"
API_BASE_URL_HTTPS = API_BASE_URL
API_LOGIN_URL = f"{API_BASE_URL}/commonrestappservice/login/format/json"
API_USER_ACCOUNT_INFO_URL = f"{API_BASE_URL_HTTPS}/restappservice/getuseraccountinfo/userid/{{user_id}}/roleID/{{role_id}}/token/{{token}}/format/json"
API_ROOMS_URL = f"{API_BASE_URL}/restappservice/getRoomPinDetails/userid/{{user_id}}/roleID/{{role_id}}/token/{{token}}/format/json"
API_PARENT_DEVICES_URL = f"{API_BASE_URL}/restappservice/index/cid/10/rid/{{role_id}}/uid/{{user_id}}/format/json"
API_RAW_DETAILS_URL = f"{API_BASE_URL}/buildtrackrestappservice/getCatRecordForAssign/format/json"

# HTTP Headers
REFERER_HEADER = "https://ezcentral.buildtrack.in/login.html"
CONTENT_TYPE_FORM = "application/x-www-form-urlencoded"

# MQTT Configuration
MQTT_BROKER_HOST = "ms.buildtrack.in"
MQTT_BROKER_PORT = 443
MQTT_WEBSOCKET_PATH = "/mqtt"
MQTT_ORIGIN = "https://ezcentral.buildtrack.in"
MQTT_PROTOCOL = "mqtt"
# Keepalive for the cloud WebSocket broker. Kept comfortably high so a brief
# latency spike does not trip the broker's 1.5x-keepalive idle timeout. The web
# client uses a similar value.
MQTT_KEEPALIVE = 60
# Select/loop timeout passed to loop_forever(). This MUST be well below
# MQTT_KEEPALIVE: paho only runs its keepalive check (and sends PINGREQ) after
# each select() returns, so a timeout >= keepalive delays the ping past the
# broker's deadline and causes constant disconnects (codes 7 / 16). 1s is the
# paho default and leaves plenty of headroom under the 60s keepalive.
MQTT_TIMEOUT = 1

# Timeouts
API_REQUEST_TIMEOUT = 10

# Device Pin Types
PIN_TYPE_SWITCH = ["1"]
PIN_TYPE_FAN = ["3", "4"]
PIN_TYPE_CURTAIN = ["7"]

# MQTT Client ID
MQTT_CLIENT_ID_SEPARATOR = "$$$"
