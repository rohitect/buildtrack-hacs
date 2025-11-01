"""BuildTrack Device Manager for handling MQTT and WebSocket connections."""
from __future__ import annotations

import json
import logging
import random
import ssl
import string
import threading
from typing import TYPE_CHECKING, Any

import aiohttp
import asyncio
import paho.mqtt.client as mqtt
import websocket

from .common import Singleton
from .const import (
    MQTT_BROKER_HOST,
    MQTT_BROKER_PORT,
    MQTT_WEBSOCKET_PATH,
    MQTT_ORIGIN,
    MQTT_PROTOCOL,
    MQTT_KEEPALIVE,
    MQTT_TIMEOUT,
    MQTT_MIN_RECONNECT_DELAY,
    MQTT_MAX_RECONNECT_DELAY,
    WS_URL,
    WS_ORIGIN,
    WS_PING_INTERVAL,
    WS_PING_TIMEOUT,
    WS_PING_PAYLOAD,
    HTTP_TIMEOUT,
)

if TYPE_CHECKING:
    from .buildtrack_api import BuildTrackAPI

_LOGGER = logging.getLogger(__name__)


class BuildTrackDeviceManager(metaclass=Singleton):
    """Manages the state of all buildtrack devices via MQTT and WebSocket."""

    def __init__(
        self,
        user_id: str,
        mqtt_username: str,
        mqtt_password: str,
        mqtt_client_id: str | None = None,
        api_reference: BuildTrackAPI | None = None
    ) -> None:
        """Initialize the Build Track State Manager."""
        self.user_id = user_id
        self.mqtt_username = mqtt_username
        self.mqtt_password = mqtt_password
        self.mqtt_client_id = mqtt_client_id or self._generate_random_client_name()
        self.api_reference = api_reference

        # State management
        self.mac_id_wise_state: dict[str, dict[str, dict[str, int]]] = {}
        self.is_websocket_connected = False
        self.is_mqtt_connected = False
        self.pending_listening_devices: set[str] = set()
        self.device_mqtt_mac_ids: list[str] = []

        # Connection objects
        self.mqtt_client: mqtt.Client | None = None
        self.websocket_connection: websocket.WebSocketApp | None = None
        self.mqtt_thread: threading.Thread | None = None
        self.wst: threading.Thread | None = None

        # Task tracking
        self._http_tasks: set[asyncio.Task] = set()

        # Initialize connections
        self.connect_to_buildtrack_tcp_server()
        self.connect_to_buildtrack_mqtt_server()

    @staticmethod
    def _generate_random_client_name(length: int = 16) -> str:
        """Generate a random client name."""
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

    def _build_command(
        self,
        mac_id: str,
        pin_number: str,
        state: str,
        speed: int | None = None
    ) -> str:
        """Build a command JSON string for device control.

        Args:
            mac_id: The MAC ID of the device
            pin_number: The pin number to control
            state: The state to set ("on", "off", "open", "close", "stop")
            speed: Optional speed value (0-100)

        Returns:
            JSON string command
        """
        params = {"pin": pin_number, "state": state}
        if speed is not None:
            params["speed"] = str(speed)
        else:
            params["speed"] = "0"

        command = {
            "macID": mac_id,
            "event": "execute",
            "command": "execute",
            "params": [params],
            "passcode": mac_id,
            "to": mac_id,
        }
        return json.dumps(command)

    def listen_to_tcp_device_status(self, mac_id):
        """Listen to buildtrack device status over websocket."""
        if self.websocket_connection is not None:
            # if mac_id not in self.mac_id_wise_state:
            if not self.is_websocket_connected:
                self.pending_listening_devices.add(mac_id)
                return
            self.mac_id_wise_state[mac_id] = {}
            try:
                self.websocket_connection.send(f'42["joinGroup","{mac_id}"]')
                self.websocket_connection.send(
                    '42["connectivityStatus","{"entityID":"'
                    + mac_id
                    + '","event":"connectivityStatus"}"]'
                )
                message = json.dumps(
                    [
                        "event_push",
                        json.dumps(
                            {
                                "macID": mac_id,
                                "event": "execute",
                                "command": "deviceStatus",
                                "params": 0,
                                "passcode": mac_id,
                                "to": mac_id,
                            }
                        ),
                    ]
                )
                self.websocket_connection.send("42" + message)
            except Exception as ex:
                self.pending_listening_devices.add(mac_id)
                _LOGGER.debug("Exception while registering device listener for " + mac_id)
                _LOGGER.debug(ex)

    def manual_device_state_update(self, mac_id, pin_number, state: bool):
        """Update the device status until the websocket response arrives manually."""
        if mac_id in self.mac_id_wise_state:
            # _LOGGER.debug(self.mac_id_wise_state[mac_id])
            # _LOGGER.debug(str(pin_number))
            # _LOGGER.debug(state)

            self.mac_id_wise_state[mac_id][f"{pin_number}"]["state"] = 1 if state else 0

    def call_local_http_api(self, mac_id, pin_number, state, speed=None):
        """Call the local HTTP API on the device's node_local_ip."""
        if not self.api_reference:
            _LOGGER.debug("API reference not available, skipping local HTTP call")
            return

        # Find the device_id from mac_id
        device_id = None
        for dev_id, device in self.api_reference.device_parent_ids_map.items():
            if device.get("mac_id") == mac_id:
                device_id = dev_id
                break

        if not device_id:
            _LOGGER.debug(f"Device ID not found for mac_id: {mac_id}")
            return

        # Get node_local_ip
        node_local_ip = self.api_reference.get_node_local_ip_for_device(device_id)
        if not node_local_ip:
            _LOGGER.debug(f"node_local_ip not available for device {device_id}")
            return

        # Prepare the payload
        payload = {
            "command": "execute",
            "params": [
                {
                    "pin": str(pin_number),
                    "state": state
                }
            ],
            "passcode": mac_id
        }

        # Add speed if provided
        if speed is not None:
            payload["params"][0]["speed"] = str(speed)

        # Schedule the async HTTP call in a separate task
        url = f"http://{node_local_ip}/execute"
        task = asyncio.create_task(self._async_http_call(url, payload, mac_id))
        self._http_tasks.add(task)
        task.add_done_callback(self._http_tasks.discard)

    async def _async_http_call(self, url, payload, mac_id):
        """Make async HTTP POST request to device."""
        try:
            _LOGGER.debug(f"Calling local HTTP API: {url}")
            timeout = aiohttp.ClientTimeout(total=2)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    headers={'Content-Type': 'text/plain; charset=utf-8'},
                    json=payload
                ) as response:
                    _LOGGER.debug(f"Local HTTP API response: {response.status}")
        except asyncio.TimeoutError:
            _LOGGER.debug(f"Timeout calling local HTTP API for {mac_id}")
        except Exception as ex:
            _LOGGER.debug(f"Error calling local HTTP API for {mac_id}: {ex}")

    def register_all_tcp_devices_listeners(self):
        """Register the listeners for all the devices upon new connection."""
        for device_mac in self.mac_id_wise_state:
            self.listen_to_tcp_device_status(device_mac)

    def register_pending_tcp_devices_listeners(self):
        """Register the listeners for the pending devices upon new connection."""
        tmp_list = self.pending_listening_devices.copy()
        self.pending_listening_devices.clear()
        for device_mac in tmp_list:
            self.listen_to_tcp_device_status(device_mac)

    def mqtt_subscribe_to_device_state(self, mac_id):
        # _LOGGER.debug("is_mqtt_connected: " + str(self.is_mqtt_connected))
        if self.is_mqtt_connected:
            _LOGGER.debug("MQTT: Subscribing to status for " + str(mac_id))
            self.mqtt_client.subscribe(mac_id + "/status")

            _LOGGER.debug("MQTT: Fetching Initial Device Status " + str(mac_id))
            # Publish the below message to fetch the device status
            self.mqtt_client.publish(f"{mac_id}/execute", payload=json.dumps({
                "macID": mac_id,
                "event": "execute",
                "command": "deviceStatus",
                "params": 0,
                "passcode": mac_id,
                "to": mac_id
            }))

    def connect_to_buildtrack_mqtt_server(self) -> None:
        """Connect to Buildtrack MQTT Server via WebSocket."""
        _LOGGER.debug("Connecting to Buildtrack MQTT Server via WebSocket")
        try:
            _LOGGER.debug(f"Using MQTT Client ID: {self.mqtt_client_id}")

            # Create MQTT client with WebSocket transport
            # Using MQTTv31 (protocol version 3) and WebSocket transport
            self.mqtt_client = mqtt.Client(
                client_id=self.mqtt_client_id,
                clean_session=False,  # Persistent session
                protocol=mqtt.MQTTv31,  # Use version 3 as per working config
                transport="websockets",  # Use WebSocket transport
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1
            )

            # The callback for when the client receives a CONNACK response from the server.
            def on_connect(client, userdata, flags, rc):
                if rc == 0:
                    _LOGGER.info("Buildtrack MQTT Server connected successfully via WebSocket")
                else:
                    _LOGGER.error(f"Buildtrack MQTT Server connection failed with result code {rc}")
                    return

                # Subscribing in on_connect() means that if we lose the connection and
                # reconnect then subscriptions will be renewed.

                # this is mainly to support websocket via mqtt
                _LOGGER.debug("Sending WillMsg ....")
                client.publish("WillMsg", payload="Connection Closed abnormally..!")

                _LOGGER.debug("MQTT (On Connect): Subscribing to " + str(len(self.device_mqtt_mac_ids))+" devices statuses...")

                self.is_mqtt_connected = True
                for mac_id in self.device_mqtt_mac_ids:
                    _LOGGER.debug("MQTT (On Connect): Subscribing to status for " + str(mac_id))
                    client.subscribe(mac_id + "/status")

                    _LOGGER.debug("MQTT: Fetching Initial Device Status " + str(mac_id))
                    # Publish the below message to fetch the device status
                    client.publish(f"{mac_id}/execute", payload=json.dumps({
                        "macID": mac_id,
                        "event": "execute",
                        "command": "deviceStatus",
                        "params": 0,
                        "passcode": mac_id,
                        "to": mac_id
                    }))

            # The callback for when a PUBLISH message is received from the server.
            def on_message(client, userdata, msg):
                _LOGGER.debug("MQTT: Message received on " + msg.topic + " : " + str(msg.payload))
                topic = str(msg.topic)
                message = str(msg.payload.decode("utf-8"))
                decoded_message = json.loads(message)
                _LOGGER.debug(decoded_message)
                self.update_switch_state(decoded_message)

            def on_log(client, userdata, level, buf):
                _LOGGER.debug("log: ", buf)

            def on_disconnect(client, userdata, rc):
                _LOGGER.debug(f"Buildtrack MQTT Server Disconnected with code: {rc}")
                self.is_mqtt_connected = False
                if rc != 0:
                    _LOGGER.debug("Unexpected MQTT disconnection. Will auto-reconnect")

            # Set callbacks
            self.mqtt_client.on_connect = on_connect
            self.mqtt_client.on_message = on_message
            # self.mqtt_client.on_log = on_log
            self.mqtt_client.on_disconnect = on_disconnect

            # DO NOT set username and password - authenticate via client ID only
            # self.mqtt_client.username_pw_set(self.mqtt_username, self.mqtt_password)

            # Enable automatic reconnection
            self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=120)

            # Set Last Will and Testament
            self.mqtt_client.will_set("WillMsg", "Connection Closed abnormally..!", qos=0, retain=False)

            # Configure TLS/SSL for WSS connection
            self.mqtt_client.tls_set(
                cert_reqs=ssl.CERT_NONE,  # Don't verify certificate
                tls_version=ssl.PROTOCOL_TLS
            )
            self.mqtt_client.tls_insecure_set(True)  # Allow insecure connection
            _LOGGER.debug("Using WSS (insecure - no certificate verification)")

            # Set WebSocket path and headers - matching browser exactly
            self.mqtt_client.ws_set_options(
                path=MQTT_WEBSOCKET_PATH,
                headers={
                    "Origin": MQTT_ORIGIN,
                    "Sec-WebSocket-Protocol": MQTT_PROTOCOL
                }
            )

            # Connect to broker using WebSocket on port 443
            _LOGGER.debug(f"Attempting to connect to {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT} via WebSocket")
            self.mqtt_client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=MQTT_KEEPALIVE)

            # Start the network loop in a separate thread
            self.mqtt_thread = threading.Thread(
                target=self.mqtt_client.loop_forever,
                kwargs={"timeout": MQTT_TIMEOUT},
            )
            self.mqtt_thread.daemon = True
            self.mqtt_thread.start()
            _LOGGER.debug("MQTT WebSocket thread started successfully")

        except Exception as ex:
            _LOGGER.error(f"Failed to connect to Buildtrack MQTT Server: {ex}")
            self.is_mqtt_connected = False

    def connect_to_buildtrack_tcp_server(self):
        """Connect to buildtrack webserver via websocket."""
        self.websocket_connection = websocket.WebSocketApp(
            "wss://ms.buildtrack.in/service/socket/?authenticate=4nedc2xrPQcphbqH45Eo&EIO=3&transport=websocket",
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            header={"Origin": "http://ezcentral.buildtrack.in"},
        )
        wst = threading.Thread(
            target=self.websocket_connection.run_forever,
            kwargs={"ping_timeout": 20, "ping_payload": "2", "ping_interval": 25},
        )
        wst.daemon = True
        wst.start()
        # self.websocket_connection.run_forever(ping_interval=25, ping_timeout=20, ping_payload='2')

    def is_device_on(self, mac_id, pin_number) -> bool:
        """Check if the device stats is on or off."""
        return not (
                mac_id not in self.mac_id_wise_state
                or f"{pin_number}" not in self.mac_id_wise_state[mac_id]
                or self.mac_id_wise_state[mac_id][f"{pin_number}"]["state"] == 0
        )

    def on_message(self, websocket_con, message: str):
        """Process the input message over websocket."""
        if message == "40":
            self.is_websocket_connected = True
            self.register_pending_tcp_devices_listeners()

        actual_data = None
        if message.startswith("42"):
            actual_data = message[2:]
        if actual_data is not None:
            decoded_message = json.loads(actual_data)
            if decoded_message[0] == "status":
                self.update_switch_state(decoded_message[1])

    def fetch_device_state(self, mac_id: str, pin_number: str) -> dict[str, int]:
        """return the device state object"""
        if (
                mac_id not in self.mac_id_wise_state
                or f"{pin_number}" not in self.mac_id_wise_state[mac_id]
        ):
            return {"state": 0, "speed": 0}

        return self.mac_id_wise_state[mac_id][f"{pin_number}"]

    def update_switch_state(self, decoded_message):
        """Update the switch state on the buildtrack server."""
        _LOGGER.debug(decoded_message)
        if decoded_message["command"] == "status":
            if decoded_message["uid"] not in self.mac_id_wise_state:
                # if decoded_message["uid"] == "40F5200DCF2D":
                # _LOGGER.debug(decoded_message["uid"] + " not in mac_id_wise_state")
                self.mac_id_wise_state[decoded_message["uid"]] = {}
            # if decoded_message["uid"] == "40F5200DCF2D":
            _LOGGER.debug(decoded_message)
            for index, item in enumerate(decoded_message["pin"]):
                if isinstance(item, dict):
                    self.mac_id_wise_state[decoded_message["uid"]][f"{index + 1}"] = {
                        "state": int(item["state"]),
                        "speed": int(item["speed"]),
                    }
                else:
                    self.mac_id_wise_state[decoded_message["uid"]][f"{index + 1}"] = {
                        "state": int(item)
                    }

    def _send_command(self, mac_id: str, command_json: str) -> None:
        """Send command via MQTT or TCP.

        Args:
            mac_id: The MAC ID of the device
            command_json: The JSON command string to send
        """
        if mac_id in self.device_mqtt_mac_ids:
            _LOGGER.debug("Sending command via MQTT")
            self.mqtt_client.publish(f"{mac_id}/execute", payload=command_json)
        else:
            _LOGGER.debug("Sending command via TCP")
            message = json.dumps(["event_push", command_json])
            self.websocket_connection.send("42" + message)

    def switch_on(self, mac_id: str, pin_number: str, speed: int | None = None) -> None:
        """Switch on the device."""
        _LOGGER.debug(f"Switching on {mac_id} with speed={speed}")

        # Build command
        command_json = self._build_command(mac_id, pin_number, "on", speed)

        # Call local HTTP API
        self.call_local_http_api(mac_id, pin_number, "on", speed)

        # Send command via MQTT or TCP
        self._send_command(mac_id, command_json)

        # Update local state
        self.manual_device_state_update(mac_id, pin_number, True)

    def switch_off(self, mac_id: str, pin_number: str, speed: int | None = None) -> None:
        """Switch off the device."""
        _LOGGER.debug(f"Switching off {mac_id}")

        # Build command
        command_json = self._build_command(mac_id, pin_number, "off", speed)

        # Call local HTTP API
        self.call_local_http_api(mac_id, pin_number, "off", speed)

        # Send command via MQTT or TCP
        self._send_command(mac_id, command_json)

        # Update local state
        self.manual_device_state_update(mac_id, pin_number, False)

    def set_cover_state(self, mac_id: str, pin_number: str, state: str = "open") -> None:
        """Set cover state (open/close/stop)."""
        # Build command
        command_json = self._build_command(mac_id, pin_number, state, speed=0)

        # Call local HTTP API
        self.call_local_http_api(mac_id, pin_number, state, speed=0)

        # Send command via MQTT or TCP
        self._send_command(mac_id, command_json)

        # Update local state (covers don't have a simple on/off state)
        self.manual_device_state_update(mac_id, pin_number, False)

    def on_error(self, websocket_con, error):
        """Handle websocket error."""
        _LOGGER.debug(f"WebSocket error: {error}")

    def on_close(self, websocket_con, close_status_code, close_msg):
        """Handle websocket closed."""
        _LOGGER.debug(f"WebSocket closed with code {close_status_code}: {close_msg}")
        self.is_websocket_connected = False
        self.connect_to_buildtrack_tcp_server()

    def on_open(self, websocket_con):
        """Handle websocket connection open."""
        _LOGGER.debug("Connected to buildtrack server....")
        websocket_con.send(f'42["login","{self.user_id}"]')
        self.register_all_tcp_devices_listeners()
