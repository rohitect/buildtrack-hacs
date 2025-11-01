"""This is wrapper class for interacting with buildtrack server."""
from __future__ import annotations

import json
import base64
import time
import logging
from typing import Any

import aiohttp

from .buildtrack_device_manager import BuildTrackDeviceManager
from .common import Singleton
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


class BuildTrackAPI(metaclass=Singleton):
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
                    headers={
                        "content-type": CONTENT_TYPE_FORM,
                        "referer": REFERER_HEADER
                    },
                    data=f"useremail={self.username}&userpassword={self.password}&rememberme=true&type=authenticate",
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
                        api_reference=self
                    )
                    return True
        except Exception as ex:
            _LOGGER.error(f"Authentication exception: {ex}")
            return False

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

                    # Remove empty rooms
                    filtered_rooms = filter(
                        lambda x: len(x["loads"]) > 0, data.get("rooms", [])
                    )

                    # Fetch all active devices
                    all_active_devices = []
                    for room in filtered_rooms:
                        loads = []
                        for load in room["loads"]:
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
        except Exception as ex:
            _LOGGER.error(f"Failed to load device raw details: {ex}")

    def _get_device_info(self, device_id: str) -> tuple[str, str]:
        """Helper method to get mac_id and pin_number for a device.

        Args:
            device_id: The device ID

        Returns:
            Tuple of (mac_id, pin_number)
        """
        parent_id = self.devices_by_room[device_id]["parentrecordID"]
        mac_id = self.device_parent_ids_map[parent_id]["mac_id"]
        pin_number = self.device_raw_details_map[device_id]["pin_number"]
        return mac_id, pin_number

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
        mac_id, pin_number = self._get_device_info(device_id)
        return self.device_state_manager.fetch_device_state(mac_id, pin_number)

    async def switch_on(self, device_id: str, speed: int | None = None) -> None:
        """Turn the device on."""
        mac_id, pin_number = self._get_device_info(device_id)
        self.device_state_manager.switch_on(mac_id, pin_number, speed)

    async def switch_off(self, device_id: str, speed: int | None = None) -> None:
        """Turn the device off."""
        mac_id, pin_number = self._get_device_info(device_id)
        self.device_state_manager.switch_off(mac_id, pin_number, speed)

    def open_cover(self, device_id: str) -> None:
        """Open the cover."""
        mac_id, pin_number = self._get_device_info(device_id)
        self.device_state_manager.set_cover_state(mac_id, pin_number, state="open")

    def close_cover(self, device_id: str) -> None:
        """Close the cover."""
        mac_id, pin_number = self._get_device_info(device_id)
        self.device_state_manager.set_cover_state(mac_id, pin_number, state="close")

    def stop_cover(self, device_id: str) -> None:
        """Stop the cover."""
        mac_id, pin_number = self._get_device_info(device_id)
        self.device_state_manager.set_cover_state(mac_id, pin_number, state="stop")

    def is_device_on(self, device_id: str) -> bool:
        """Check if the device is on or not."""
        if device_id not in self.devices_by_room:
            return False
        mac_id, pin_number = self._get_device_info(device_id)
        return self.device_state_manager.is_device_on(mac_id, pin_number)

    async def toggle_device(self, device_id: str) -> None:
        """Toggle the device state."""
        if self.is_device_on(device_id):
            await self.switch_off(device_id)
        else:
            await self.switch_on(device_id)

    def listen_device_state(self, device_id: str) -> None:
        """Listen for device state."""
        parent_id = self.devices_by_room[device_id]["parentrecordID"]
        mac_id = self.device_parent_ids_map[parent_id]["mac_id"]

        # Check if the device is on MQTT or not
        if self.is_device_on_mqtt(parent_id):
            self.device_state_manager.device_mqtt_mac_ids.append(mac_id)
            self.device_state_manager.mqtt_subscribe_to_device_state(mac_id)
        else:
            self.device_state_manager.listen_to_tcp_device_status(mac_id)
