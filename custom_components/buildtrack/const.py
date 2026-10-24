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
# Keepalive for the cloud WebSocket broker. This MUST stay well below 60s: the
# WebSocket front end of ms.buildtrack.in closes any connection that has been
# idle for 60s, regardless of the MQTT keepalive. With keepalive=60 the first
# PINGREQ is due exactly at that cutoff, so the socket is dropped (code 7)
# roughly every 60s. Verified by probing the broker: keepalive=60 drops at
# 60.2s every time, keepalive=30 stays up with PINGREQ/PINGRESP every 30s.
MQTT_KEEPALIVE = 30
# The network loop runs via paho's loop_start(), which uses paho's default 1s
# select timeout. That must stay well below MQTT_KEEPALIVE: paho only sends
# PINGREQ after each select() returns, so a timeout >= keepalive delays the
# ping past the broker's deadline (disconnect codes 7 / 16).

# Commands issued while MQTT is down are queued and flushed on reconnect.
# Queued commands older than this are dropped rather than replayed, so a light
# doesn't unexpectedly change state long after it was asked to.
MQTT_COMMAND_QUEUE_TTL = 30
# A QoS 0 publish written just before the socket drops can be lost silently.
# On an unexpected disconnect, commands published within this many seconds are
# re-queued and resent on reconnect. Commands set absolute states (on/off/
# open/close/stop), so resending one is harmless.
MQTT_RESEND_WINDOW = 3

# Timeouts
API_REQUEST_TIMEOUT = 10

# Device Pin Types
PIN_TYPE_SWITCH = ["1"]
PIN_TYPE_FAN = ["3", "4"]
PIN_TYPE_CURTAIN = ["7"]

# MQTT Client ID
MQTT_CLIENT_ID_SEPARATOR = "$$$"
