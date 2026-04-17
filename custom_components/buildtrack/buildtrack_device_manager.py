"""BuildTrack Device Manager for handling MQTT and local HTTP control."""
from __future__ import annotations

import json
import logging
import random
import ssl
import string
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

import aiohttp
import asyncio
import paho.mqtt.client as mqtt

from .const import (
    MQTT_BROKER_HOST,
    MQTT_BROKER_PORT,
    MQTT_WEBSOCKET_PATH,
    MQTT_ORIGIN,
    MQTT_PROTOCOL,
    MQTT_KEEPALIVE,
    MQTT_TIMEOUT,
)

if TYPE_CHECKING:
    from .buildtrack_api import BuildTrackAPI

_LOGGER = logging.getLogger(__name__)


class BuildTrackDeviceManager:
    """Manages the state of all buildtrack devices via MQTT and local HTTP."""

    def __init__(
        self,
        user_id: str,
        mqtt_username: str,
        mqtt_password: str,
        mqtt_client_id: str | None = None,
        api_reference: BuildTrackAPI | None = None,
        token: str | None = None,
    ) -> None:
        """Initialize the Build Track State Manager."""
        self.user_id = user_id
        self.mqtt_username = mqtt_username
        self.mqtt_password = mqtt_password
        self.mqtt_client_id = mqtt_client_id or self._generate_random_client_name()
        self.api_reference = api_reference
        self.token = token

        # State management
        self.mac_id_wise_state: dict[str, dict[str, dict[str, int]]] = {}
        self.is_mqtt_connected = False
        self.device_mqtt_mac_ids: list[str] = []

        # Connection objects
        self.mqtt_client: mqtt.Client | None = None
        self.mqtt_thread: threading.Thread | None = None

        # Task tracking
        self._http_tasks: set[asyncio.Task] = set()
        self._shutting_down = False

        # State change callbacks: keyed by "{mac_id}_{pin_number}"
        self._state_callbacks: dict[str, list[Callable[[], None]]] = {}

        # Connections are initialized via connect() to allow running off the event loop

    def connect(self) -> None:
        """Initialize MQTT connection. Call from executor thread."""
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

    def register_callback(
        self, mac_id: str, pin_number: str, callback: Callable[[], None]
    ) -> None:
        """Register a callback for state changes on a specific device pin."""
        key = f"{mac_id}_{pin_number}"
        self._state_callbacks.setdefault(key, []).append(callback)

    def remove_callback(
        self, mac_id: str, pin_number: str, callback: Callable[[], None]
    ) -> None:
        """Remove a previously registered callback."""
        key = f"{mac_id}_{pin_number}"
        if key in self._state_callbacks:
            self._state_callbacks[key] = [
                cb for cb in self._state_callbacks[key] if cb is not callback
            ]

    def _notify_callbacks(self, mac_id: str, pin_number: str) -> None:
        """Notify all registered callbacks for a device pin."""
        key = f"{mac_id}_{pin_number}"
        for callback in self._state_callbacks.get(key, []):
            try:
                callback()
            except Exception as ex:
                _LOGGER.debug(f"Error in state callback for {key}: {ex}")

    def manual_device_state_update(self, mac_id, pin_number, state: bool):
        """Update the device status optimistically until an MQTT response arrives."""
        if mac_id in self.mac_id_wise_state:
            pin_key = f"{pin_number}"
            if pin_key not in self.mac_id_wise_state[mac_id]:
                self.mac_id_wise_state[mac_id][pin_key] = {"state": 0, "speed": 0}
            self.mac_id_wise_state[mac_id][pin_key]["state"] = 1 if state else 0

    def call_local_http_api(self, mac_id, pin_number, state, speed=None):
        """Call the local HTTP API on the device's node_local_ip."""
        if not self.api_reference:
            _LOGGER.info("Local HTTP: skipped (no API reference) for mac=%s", mac_id)
            return

        # Find the device_id from mac_id
        device_id = None
        for dev_id, device in self.api_reference.device_parent_ids_map.items():
            if device.get("mac_id") == mac_id:
                device_id = dev_id
                break

        if not device_id:
            _LOGGER.info("Local HTTP: skipped (no device found for mac=%s)", mac_id)
            return

        # Get node_local_ip
        node_local_ip = self.api_reference.get_node_local_ip_for_device(device_id)
        if not node_local_ip:
            _LOGGER.info("Local HTTP: skipped (no local IP for device=%s mac=%s)", device_id, mac_id)
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

        # '{"command":"execute","params":[{"pin":"1","state":"on","speed":"75"}],"passcode":"AC0BFBF187DE"}'

        # Add speed if provided
        if speed is not None:
            payload["params"][0]["speed"] = str(speed)

        _LOGGER.info("Payload : %s", payload)    

        # Schedule the async HTTP call in a separate task
        url = f"http://{node_local_ip}/execute"
        _LOGGER.info("Local HTTP: sending to %s (mac=%s pin=%s state=%s)", url, mac_id, pin_number, state)
        task = asyncio.create_task(self._async_http_call(url, payload, mac_id))
        self._http_tasks.add(task)
        task.add_done_callback(self._http_tasks.discard)

    async def _async_http_call(self, url, payload, mac_id):
        """Make async HTTP POST request to device."""
        try:
            timeout = aiohttp.ClientTimeout(total=2)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    headers={'Content-Type': 'text/plain; charset=utf-8'},
                    json=payload
                ) as response:
                    _LOGGER.info("Local HTTP: response %s from %s", response.status, url)
        except asyncio.TimeoutError:
            _LOGGER.warning("Local HTTP: timeout calling %s (mac=%s)", url, mac_id)
        except Exception as ex:
            _LOGGER.warning("Local HTTP: error calling %s (mac=%s): %s", url, mac_id, ex)

    def mqtt_subscribe_to_device_state(self, mac_id):
        """Subscribe to device status topic and request initial state via MQTT."""
        # Initialize state dict so is_device_on() doesn't default to False
        self.mac_id_wise_state.setdefault(mac_id, {})

        if not self.is_mqtt_connected or self.mqtt_client is None:
            return

        _LOGGER.debug("MQTT: Subscribing to %s/status", mac_id)
        self.mqtt_client.subscribe(f"{mac_id}/status")

        _LOGGER.debug("MQTT: Requesting deviceStatus for %s", mac_id)
        self.mqtt_client.publish(f"{mac_id}/execute", payload=json.dumps({
            "macID": mac_id,
            "event": "execute",
            "command": "deviceStatus",
            "params": 0,
            "passcode": mac_id,
            "to": mac_id,
        }))

    def _handle_pin_status(self, mac_id: str, payload: dict) -> None:
        """Handle a pinStatus MQTT message for a specific device."""
        _LOGGER.debug("MQTT pinStatus for %s: %s", mac_id, payload)

        # If the payload already looks like a full status message, reuse existing parser
        if isinstance(payload, dict) and payload.get("command") == "status":
            self.update_switch_state(payload)
            return

        # Otherwise try to extract pin array directly
        pins = None
        if isinstance(payload, dict):
            pins = payload.get("pin") or payload.get("pins")
        elif isinstance(payload, list):
            pins = payload

        if pins is None:
            _LOGGER.debug("MQTT pinStatus: no pin data found for %s, payload: %s", mac_id, payload)
            return

        # Synthesise a status message in the same format update_switch_state expects
        self.update_switch_state({"command": "status", "uid": mac_id, "pin": pins})

    def _handle_execution_status(self, payload) -> None:
        """Handle an executionStatus MQTT message (command result or bulk device state)."""
        _LOGGER.debug("MQTT executionStatus: %s", payload)

        if isinstance(payload, list):
            # Bulk response: list of device status objects
            for item in payload:
                if isinstance(item, dict) and item.get("command") == "status":
                    self.update_switch_state(item)
        elif isinstance(payload, dict):
            if payload.get("command") == "status":
                self.update_switch_state(payload)
            # If it's a command ack (e.g. {"command": "execute", ...}), nothing to update

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
                if rc != 0:
                    _LOGGER.error("Buildtrack MQTT Server connection failed with result code %d", rc)
                    return

                _LOGGER.info("Buildtrack MQTT Server connected successfully via WebSocket")
                self.is_mqtt_connected = True

                # Subscribing in on_connect() means subscriptions are renewed on reconnect.
                client.publish("WillMsg", payload="Connection Closed abnormally..!")

                if not self.token:
                    _LOGGER.error("MQTT: No token available — cannot subscribe to account-level topics")
                    return

                # Subscribe to account-level topics for real-time push updates
                topics = [
                    (f"executionStatus/{self.token}", 0),
                    (f"{self.token}/#", 0),
                    (f"pinStatus/{self.token}/#", 0),
                    (f"nodeStatus/{self.token}/#", 0),
                    (f"connectivityStatus/{self.token}", 0),
                ]
                _LOGGER.debug("MQTT: Subscribing to %d account-level topics", len(topics))
                client.subscribe(topics)

                # Per-device: subscribe to {mac_id}/status and request current state
                for mac_id in self.device_mqtt_mac_ids:
                    # _LOGGER.debug("MQTT: Subscribing to %s/status and requesting deviceStatus", mac_id)
                    client.subscribe(f"{mac_id}/status")
                    client.publish(f"{mac_id}/execute", payload=json.dumps({
                        "macID": mac_id,
                        "event": "execute",
                        "command": "deviceStatus",
                        "params": 0,
                        "passcode": mac_id,
                        "to": mac_id,
                    }))

            # The callback for when a PUBLISH message is received from the server.
            def on_message(client, userdata, msg):
                topic: str = msg.topic
                raw = msg.payload.decode("utf-8")
                # _LOGGER.debug("MQTT RAW: topic=%s payload=%s", topic, raw)

                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    _LOGGER.debug("MQTT: non-JSON payload on %s, ignoring", topic)
                    return

                token_prefix = self.token or ""

                if topic.startswith(f"pinStatus/{token_prefix}/"):
                    # Topic: pinStatus/{token}/{mac_id}
                    mac_id = topic.split("/", 2)[2]
                    self._handle_pin_status(mac_id, payload)

                elif topic.startswith(f"nodeStatus/{token_prefix}/"):
                    # Topic: nodeStatus/{token}/{mac_id} — connectivity / online status
                    mac_id = topic.split("/", 2)[2]
                    _LOGGER.debug("MQTT: nodeStatus for %s: %s", mac_id, payload)

                elif topic == f"executionStatus/{token_prefix}":
                    # Execution result from a command or getExecutionStatus response
                    self._handle_execution_status(payload)

                elif topic == f"connectivityStatus/{token_prefix}":
                    _LOGGER.debug("MQTT: connectivityStatus: %s", payload)

                else:
                    # Covers {mac_id}/status and any other topics
                    # _LOGGER.debug("MQTT device status: topic=%s payload=%s", topic, payload)
                    if isinstance(payload, dict) and payload.get("command") == "status":
                        self.update_switch_state(payload)

            def on_disconnect(client, userdata, rc):
                _LOGGER.warning("Buildtrack MQTT Server Disconnected with code: %s", rc)
                self.is_mqtt_connected = False

            # Set callbacks
            self.mqtt_client.on_connect = on_connect
            self.mqtt_client.on_message = on_message
            self.mqtt_client.on_disconnect = on_disconnect

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

    def is_device_on(self, mac_id, pin_number) -> bool:
        """Check if the device stats is on or off."""
        return not (
                mac_id not in self.mac_id_wise_state
                or f"{pin_number}" not in self.mac_id_wise_state[mac_id]
                or self.mac_id_wise_state[mac_id][f"{pin_number}"]["state"] == 0
        )

    def fetch_device_state(self, mac_id: str, pin_number: str) -> dict[str, int]:
        """return the device state object"""
        if (
                mac_id not in self.mac_id_wise_state
                or f"{pin_number}" not in self.mac_id_wise_state[mac_id]
        ):
            return {"state": 0, "speed": 0}

        return self.mac_id_wise_state[mac_id][f"{pin_number}"]

    def update_switch_state(self, decoded_message):
        """Update the switch state from an MQTT status message."""
        # _LOGGER.debug(decoded_message)
        if decoded_message["command"] == "status":
            mac_id = decoded_message["uid"]
            if mac_id not in self.mac_id_wise_state:
                self.mac_id_wise_state[mac_id] = {}
            # _LOGGER.debug(decoded_message)
            for index, item in enumerate(decoded_message["pin"]):
                pin_number = f"{index + 1}"
                if isinstance(item, dict):
                    self.mac_id_wise_state[mac_id][pin_number] = {
                        "state": int(item["state"]),
                        "speed": int(item["speed"]),
                    }
                else:
                    self.mac_id_wise_state[mac_id][pin_number] = {
                        "state": int(item)
                    }
                self._notify_callbacks(mac_id, pin_number)

    def _send_command(self, mac_id: str, command_json: str) -> None:
        """Send command via MQTT.

        Args:
            mac_id: The MAC ID of the device
            command_json: The JSON command string to send
        """
        if self.is_mqtt_connected and self.mqtt_client is not None:
            try:
                _LOGGER.info("Sending command via MQTT to %s: %s", mac_id, command_json)
                self.mqtt_client.publish(f"{mac_id}/execute", payload=command_json)
            except Exception as ex:
                _LOGGER.error("MQTT publish failed for %s: %s", mac_id, ex)
        else:
            _LOGGER.warning("MQTT not connected — skipping MQTT command for %s", mac_id)

    def switch_on(self, mac_id: str, pin_number: str, speed: int | None = None) -> None:
        """Switch on the device."""
        _LOGGER.debug("switch_on: mac=%s pin=%s speed=%s", mac_id, pin_number, speed)

        # Build command
        command_json = self._build_command(mac_id, pin_number, "on", speed)

        # Call local HTTP API
        self.call_local_http_api(mac_id, pin_number, "on", speed)

        # Send command via MQTT
        self._send_command(mac_id, command_json)

        # Update local state
        self.manual_device_state_update(mac_id, pin_number, True)

    def switch_off(self, mac_id: str, pin_number: str, speed: int | None = None) -> None:
        """Switch off the device."""
        _LOGGER.debug("switch_off: mac=%s pin=%s speed=%s", mac_id, pin_number, speed)

        # Build command
        command_json = self._build_command(mac_id, pin_number, "off", speed)

        # Call local HTTP API
        self.call_local_http_api(mac_id, pin_number, "off", speed)

        # Send command via MQTT
        self._send_command(mac_id, command_json)

        # Update local state
        self.manual_device_state_update(mac_id, pin_number, False)

    def set_cover_state(self, mac_id: str, pin_number: str, state: str = "open") -> None:
        """Set cover state (open/close/stop)."""
        _LOGGER.debug("set_cover_state: mac=%s pin=%s state=%s", mac_id, pin_number, state)
        command_json = self._build_command(mac_id, pin_number, state, speed=0)

        # Send command via MQTT
        self._send_command(mac_id, command_json)

        # Update local state (covers don't have a simple on/off state)
        self.manual_device_state_update(mac_id, pin_number, False)

    def disconnect(self) -> None:
        """Disconnect all connections and clean up resources."""
        _LOGGER.debug("Disconnecting BuildTrackDeviceManager")
        self._shutting_down = True

        # Cancel all pending HTTP tasks
        for task in self._http_tasks:
            task.cancel()
        self._http_tasks.clear()

        # Disconnect MQTT (causes loop_forever to return, ending the thread)
        if self.mqtt_client is not None:
            mqtt_client = self.mqtt_client
            self.mqtt_client = None
            try:
                # Disable auto-reconnect so loop_forever exits instead of retrying
                mqtt_client.reconnect_delay_set(min_delay=999999, max_delay=999999)
                mqtt_client.disconnect()
                mqtt_client.loop_stop()
            except Exception as ex:
                _LOGGER.debug(f"Error disconnecting MQTT: {ex}")
        self.is_mqtt_connected = False

        # Wait for thread to finish
        if self.mqtt_thread is not None:
            if self.mqtt_thread.is_alive():
                self.mqtt_thread.join(timeout=5)
                if self.mqtt_thread.is_alive():
                    _LOGGER.warning(
                        "MQTT thread %s did not exit within 5s — may leak",
                        self.mqtt_thread.name,
                    )
            self.mqtt_thread = None
