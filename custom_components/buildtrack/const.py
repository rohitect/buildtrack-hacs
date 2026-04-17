"""Constants for the Buildtrack integration."""

DOMAIN = "buildtrack"

# API Endpoints
API_BASE_URL = "http://ezcentral.buildtrack.in/btadmin/index.php"
API_BASE_URL_HTTPS = "https://ezcentral.buildtrack.in/btadmin/index.php"
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
MQTT_KEEPALIVE = 10
MQTT_TIMEOUT = 20

# Timeouts
API_REQUEST_TIMEOUT = 10

# Device Pin Types
PIN_TYPE_SWITCH = ["1"]
PIN_TYPE_FAN = ["3", "4"]
PIN_TYPE_CURTAIN = ["7"]

# MQTT Client ID
MQTT_CLIENT_ID_SEPARATOR = "$$$"
