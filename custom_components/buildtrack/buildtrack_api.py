"""This is wrapper class for interacting with buildtrack server."""
from __future__ import annotations

import json
import base64
import time
import logging
from collections.abc import Callable
from typing import Any

import aiohttp

from .buildtrack_device_manager import BuildTrackDeviceManager
from .const import (
    API_LOGIN_URL,
    API_USER_ACCOUNT_INFO_URL,
    API_ROOMS_URL,
    API_PARENT_DEVICES_URL,
    API_RAW_DETAILS_URL,
    REFERER_HEADER,
    CONTENT_TYPE_FORM,
    API_REQUEST_TIMEOUT,
    PIN_TYPE_SWITCH,
    PIN_TYPE_FAN,
    PIN_TYPE_CURTAIN,
    MQTT_CLIENT_ID_SEPARATOR,
)

_LOGGER = logging.getLogger(__name__)


class BuildTrackAPI:
    """This is the wrapper class to interact with the Build Track Server."""

    def __init__(self) -> None:
        """Initialize the API class."""
        self.username = None
        self.password = None
        self.mqtt_username = None
        self.mqtt_password = None
        self.login_response = None
        self.token = None
        self.first_name = None
        self.user_id = None
        self.role_id = None
        self.credentials = None
        self.mqtt_client_id = None
        self.device_state_manager: BuildTrackDeviceManager = None
        self.device_parent_ids_map: dict = {}
        self.device_raw_details_map: dict = {}
        self.devices_by_room: dict = {}

    def set_credentials(self, username: str, password: str) -> None:
        """Set the buildtrack credentials."""
        self.username = username
        self.password = password

    def set_mqtt_creds(self, username: str, password: str) -> None:
        """Set the MQTT Credentials."""
        self.mqtt_username = username
        self.mqtt_password = password

    async def fetch_user_account_info(self) -> bool:
        """Fetch user account info and generate MQTT client ID."""
        try:
            url = API_USER_ACCOUNT_INFO_URL.format(
                user_id=self.user_id,
                role_id=self.role_id,
                token=self.token
            )
            timeout = aiohttp.ClientTimeout(total=API_REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    url,
                    headers={"referer": REFERER_HEADER}
                ) as response:
                    data = await response.json()

                    if "credentials" in data:
                        self.credentials = data["credentials"]
                        # Generate MQTT client ID as base64(credentials + $$$ + timestamp in ms)
                        timestamp_ms = int(time.time() * 1000)
                        client_id_string = f"{self.credentials}{MQTT_CLIENT_ID_SEPARATOR}{timestamp_ms}"
                        self.mqtt_client_id = base64.b64encode(client_id_string.encode()).decode()
                        _LOGGER.debug(f"Generated MQTT Client ID: {self.mqtt_client_id}")
                        return True

                    _LOGGER.error("Credentials not found in user account info response")
                    return False
        except Exception as ex:
            _LOGGER.error(f"Failed to fetch user account info: {ex}")
            return False

    async def authenticate_user(self) -> bool:
        """Authenticate the user."""
        try:
            timeout = aiohttp.ClientTimeout(total=API_REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    API_LOGIN_URL,
                    headers={"referer": REFERER_HEADER},
                    # Pass the body as a dict so aiohttp URL-encodes it. Building
                    # the form string by hand broke authentication whenever the
                    # username or password contained reserved characters such as
                    # & = + % or #. aiohttp sets the correct content-type header.
                    data={
                        "useremail": self.username,
                        "userpassword": self.password,
                        "rememberme": "true",
                        "type": "authenticate",
                    },
                ) as response:
                    data = await response.json()
                    _LOGGER.debug("Login Response")
                    _LOGGER.debug(data)

                    if data.get("status") != 1:
                        _LOGGER.error("Authentication failed")
                        return False

                    self.login_response = data
                    self.token = data["token"]
                    self.first_name = data["first_name"]
                    self.user_id = data["userid"]
                    self.role_id = data["roleID"]

                    # Fetch user account info to get credentials and generate MQTT client ID
                    if not await self.fetch_user_account_info():
                        _LOGGER.error("Failed to fetch user account info")
                        return False

                    await self.discover_devices_by_rooms()
                    await self.load_all_parent_devices()
                    await self.load_all_devices_raw_details()

                    self.device_state_manager = BuildTrackDeviceManager(
                        data["userid"],
                        self.mqtt_username,
                        self.mqtt_password,
                        self.mqtt_client_id,
                        api_reference=self,
                        token=self.token,
                    )
                    return True
        except Exception as ex:
            _LOGGER.error(f"Authentication exception: {ex}")
            return False

    def start_connections(self) -> None:
        """Start MQTT connection. Must be called from executor thread."""
        if self.device_state_manager is not None:
            self.device_state_manager.connect()

    def get_first_name(self) -> str | None:
        """Respond with the first name."""
        return self.first_name

    async def discover_devices_by_rooms(self) -> list[dict[str, Any]]:
        """Discover devices by rooms."""
        if not self.token:
            return []

        try:
            url = API_ROOMS_URL.format(
                user_id=self.user_id,
                role_id=self.role_id,
                token=self.token
            )
            timeout = aiohttp.ClientTimeout(total=API_REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    url,
                    headers={"referer": REFERER_HEADER}
                ) as response:
                    data = await response.json()

                    # Remove empty rooms. Use .get("loads") so a room without a
                    # "loads" key doesn't raise KeyError — which, being caught by
                    # the broad handler below, would silently drop ALL devices.
                    filtered_rooms = filter(
                        lambda x: len(x.get("loads") or []) > 0, data.get("rooms", [])
                    )

                    # Fetch all active devices
                    all_active_devices = []
                    for room in filtered_rooms:
                        loads = []
                        for load in room.get("loads") or []:
                            load["room_name"] = room["name"]
                            load["room_id"] = room["id"]
                            loads.append(load)
                        all_active_devices.extend(loads)

                    self.devices_by_room = {
                        device["ID"]: device for device in all_active_devices
                    }
                    return all_active_devices
        except Exception as ex:
            _LOGGER.error(f"Failed to discover devices: {ex}")
            return []

    def get_devices_of_type(self, device_type: str) -> list[dict[str, Any]]:
        """Return back all devices of a specific type.

        Args:
            device_type: "fan" | "switch" | "curtain"

        Returns:
            List of devices matching the type
        """
        pin_numbers = ["0"]
        if device_type == "fan":
            pin_numbers = PIN_TYPE_FAN
        elif device_type == "switch":
            pin_numbers = PIN_TYPE_SWITCH
        elif device_type == "curtain":
            pin_numbers = PIN_TYPE_CURTAIN

        return [
            device for device in self.devices_by_room.values()
            if device.get("pin_type") in pin_numbers
        ]

    async def load_all_parent_devices(self) -> None:
        """Load all the parent devices in the account."""
        if not self.token:
            return

        try:
            url = API_PARENT_DEVICES_URL.format(
                role_id=self.role_id,
                user_id=self.user_id
            )
            timeout = aiohttp.ClientTimeout(total=API_REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    url,
                    headers={"referer": REFERER_HEADER}
                ) as response:
                    data = await response.json()
                    self.device_parent_ids_map = {
                        device["ID"]: device for device in data
                    }
        except Exception as ex:
            _LOGGER.error(f"Failed to load parent devices: {ex}")

    async def load_all_devices_raw_details(self) -> None:
        """Load all devices raw details."""
        if not self.token:
            return

        try:
            url = f"{API_RAW_DETAILS_URL}?type=11&userid={self.user_id}&roleID={self.role_id}&token={self.token}&recordID=&defineFields=&filterID=&hierarchyFilter=&is_template=0&action=0&is_association=0&recordsonly=1&sync=1"
            timeout = aiohttp.ClientTimeout(total=API_REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    url,
                    headers={"referer": REFERER_HEADER}
                ) as response:
                    data = await response.json()
                    self.device_raw_details_map = {
                        device["ID"]: device for device in data
                    }
                    _LOGGER.debug(
                        "Loaded %d raw device details. IDs: %s",
                        len(self.device_raw_details_map),
                        list(self.device_raw_details_map.keys()),
                    )
        except Exception as ex:
            _LOGGER.error(f"Failed to load device raw details: {ex}")

    def _get_device_info(self, device_id: str) -> tuple[str, str]:
        """Helper method to get mac_id and pin_number for a device.

        Args:
            device_id: The device ID

        Returns:
            Tuple of (mac_id, pin_number)

        Raises:
            KeyError: the device is unknown.
            ValueError: the pin number cannot be resolved. We deliberately do
                NOT guess a pin here: on a multi-relay node, sending a command
                to the wrong pin would switch a completely different load (e.g.
                a geyser instead of a light), so refusing is the safe choice.
        """
        device = self.devices_by_room.get(device_id)
        if device is None:
            raise KeyError(f"Device {device_id} not found in rooms data")

        parent_id = device["parentrecordID"]
        mac_id = self.device_parent_ids_map[parent_id]["mac_id"]

        # The rooms/pin data (getRoomPinDetails) is the authoritative source for
        # the pin number — it is exactly what the BuildTrack web UI uses to build
        # its commands. Prefer it, and only fall back to the raw-details map
        # (getCatRecordForAssign type=11) when rooms data is missing a pin.
        pin_number = device.get("pin_number") or device.get("pin")
        if not pin_number and device_id in self.device_raw_details_map:
            pin_number = self.device_raw_details_map[device_id].get("pin_number")

        if not pin_number:
            raise ValueError(
                f"Could not resolve pin_number for device {device_id} "
                f"(mac={mac_id}); refusing to send a command to avoid "
                f"controlling the wrong relay"
            )

        return mac_id, str(pin_number)

    def get_parent_device_details(self, device_id: str) -> dict[str, Any] | None:
        """Get the parent device details for a given device.

        Returns dict with mac_id, name, model info, or None if not found.
        """
        if device_id not in self.devices_by_room:
            return None
        parent_id = self.devices_by_room[device_id].get("parentrecordID")
        if not parent_id or parent_id not in self.device_parent_ids_map:
            return None
        return self.device_parent_ids_map[parent_id]

    def get_mac_id_for_device(self, device_id: str) -> str | None:
        """Return back the mac id for the device."""
        if device_id in self.device_parent_ids_map:
            return self.device_parent_ids_map[device_id]["mac_id"]
        return None

    def get_node_local_ip_for_device(self, device_id: str) -> str | None:
        """Return back the node_local_ip for the device."""
        if device_id in self.device_parent_ids_map:
            return self.device_parent_ids_map[device_id].get("node_local_ip")
        return None

    def is_device_on_mqtt(self, device_id: str) -> bool:
        """Return back if the device is connected to the mqtt."""
        try:
            if device_id not in self.device_parent_ids_map:
                return False

            product_info = self.device_parent_ids_map[device_id].get("product_info", "").strip()
            if not product_info:
                return False

            decoded = json.loads(product_info)
            return "mqttState" in decoded and "1" in decoded["mqttState"]
        except (json.JSONDecodeError, KeyError):
            return False

    def get_device_state(self, device_id: str) -> dict[str, Any]:
        """Get the current state of a device."""
        try:
            mac_id, pin_number = self._get_device_info(device_id)
        except (KeyError, ValueError) as ex:
            _LOGGER.debug("get_device_state: %s", ex)
            return {"state": 0, "speed": 0}
        return self.device_state_manager.fetch_device_state(mac_id, pin_number)

    async def switch_on(self, device_id: str, speed: int | None = None) -> None:
        """Turn the device on."""
        mac_id, pin_number = self._get_device_info(device_id)
        _LOGGER.debug("API switch_on: device=%s -> mac=%s pin=%s speed=%s", device_id, mac_id, pin_number, speed)
        self.device_state_manager.switch_on(mac_id, pin_number, speed)

    async def switch_off(self, device_id: str, speed: int | None = None) -> None:
        """Turn the device off."""
        mac_id, pin_number = self._get_device_info(device_id)
        _LOGGER.debug("API switch_off: device=%s -> mac=%s pin=%s", device_id, mac_id, pin_number)
        self.device_state_manager.switch_off(mac_id, pin_number, speed)

    async def open_cover(self, device_id: str) -> None:
        """Open the cover."""
        mac_id, pin_number = self._get_device_info(device_id)
        _LOGGER.debug("API open_cover: device=%s -> mac=%s pin=%s", device_id, mac_id, pin_number)
        self.device_state_manager.set_cover_state(mac_id, pin_number, "open")

    async def close_cover(self, device_id: str) -> None:
        """Close the cover."""
        mac_id, pin_number = self._get_device_info(device_id)
        _LOGGER.debug("API close_cover: device=%s -> mac=%s pin=%s", device_id, mac_id, pin_number)
        self.device_state_manager.set_cover_state(mac_id, pin_number, "close")

    async def stop_cover(self, device_id: str) -> None:
        """Stop the cover."""
        mac_id, pin_number = self._get_device_info(device_id)
        _LOGGER.debug("API stop_cover: device=%s -> mac=%s pin=%s", device_id, mac_id, pin_number)
        self.device_state_manager.set_cover_state(mac_id, pin_number, "stop")

    def is_device_on(self, device_id: str) -> bool:
        """Check if the device is on or not."""
        if device_id not in self.devices_by_room:
            return False
        try:
            mac_id, pin_number = self._get_device_info(device_id)
        except (KeyError, ValueError) as ex:
            _LOGGER.debug("is_device_on: %s", ex)
            return False
        return self.device_state_manager.is_device_on(mac_id, pin_number)

    async def toggle_device(self, device_id: str) -> None:
        """Toggle the device state."""
        if self.is_device_on(device_id):
            await self.switch_off(device_id)
        else:
            await self.switch_on(device_id)

    def register_state_callback(
        self, device_id: str, callback: Callable[[], None]
    ) -> None:
        """Register a callback for state changes on a device."""
        try:
            mac_id, pin_number = self._get_device_info(device_id)
        except (KeyError, ValueError) as ex:
            _LOGGER.warning("Cannot register state callback for %s: %s", device_id, ex)
            return
        self.device_state_manager.register_callback(mac_id, pin_number, callback)

    def remove_state_callback(
        self, device_id: str, callback: Callable[[], None]
    ) -> None:
        """Remove a state change callback for a device."""
        try:
            mac_id, pin_number = self._get_device_info(device_id)
        except (KeyError, ValueError) as ex:
            _LOGGER.debug("Cannot remove state callback for %s: %s", device_id, ex)
            return
        self.device_state_manager.remove_callback(mac_id, pin_number, callback)

    def shutdown(self) -> None:
        """Shut down the API and clean up resources."""
        if self.device_state_manager is not None:
            self.device_state_manager.disconnect()
            self.device_state_manager = None

    def listen_device_state(self, device_id: str) -> None:
        """Listen for device state via MQTT."""
        parent_id = self.devices_by_room[device_id]["parentrecordID"]
        mac_id = self.device_parent_ids_map[parent_id]["mac_id"]

        self.device_state_manager.device_mqtt_mac_ids.append(mac_id)
        self.device_state_manager.mqtt_subscribe_to_device_state(mac_id)
