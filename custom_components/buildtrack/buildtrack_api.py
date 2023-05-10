"""This is wrapper class for interacting with buldtrack server."""
import json

import requests

from .buildtrack_device_manager import BuildTrackDeviceManager
from .common import Singleton


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
        self.device_state_manager: BuildTrackDeviceManager = None
        self.device_parent_ids_map: dict = {}
        self.device_raw_details_map: dict = {}
        self.devices_by_room: dict = {}

    def set_credentials(self, username, password):
        """Set the buildtrack credentials."""
        self.username = username
        self.password = password

    def set_mqtt_creds(self, username, password):
        """Set the MQTT Credentials"""
        self.mqtt_username = username
        self.mqtt_password = password

    def authenticate_user(self) -> bool:
        """Authenticate the user."""
        try:
            response = requests.post(
                "http://ezcentral.buildtrack.in/btadmin/index.php/commonrestappservice/login/format/json",
                headers={"content-type": "application/x-www-form-urlencoded", "referer": "https://ezcentral.buildtrack.in/login.html"},
                data=f"useremail={self.username}&userpassword={self.password}&rememberme=true&type=authenticate",
            )
            data = response.json()
            if data["status"] == 1:
                self.login_response = data
                self.token = data["token"]
                self.first_name = data["first_name"]
                self.user_id = data["userid"]
                self.role_id = data["roleID"]
                self.discover_devices_by_rooms()
                self.load_all_parent_devices()
                self.load_all_devices_raw_details()
                self.device_state_manager = BuildTrackDeviceManager(data["userid"], self.mqtt_username, self.mqtt_password)
                return True
            return False
        except ConnectionError as connection_error:
            print("Exception occurred")
            print(connection_error)
            return False

    def get_first_name(self):
        """Respond with the first name."""
        return self.first_name

    def discover_devices_by_rooms(self):
        """Discover devices by rooms."""
        # pin_number = "0"
        # if device_type == "fan":
        #     pin_number = "4"
        # elif device_type == "switch":
        #     pin_number = "1"

        # print("Discover By Rooms URL: ")
        if self.token is not None:
            response = requests.get(
                f"http://ezcentral.buildtrack.in/btadmin/index.php/restappservice/getRoomPinDetails/userid/{self.user_id}/roleID/{self.role_id}/token/{self.token}/format/json",
                headers={"referer": "https://ezcentral.buildtrack.in/login.html"}
            )
            # remove the empty rooms
            filtered_rooms = filter(
                lambda x: len(x["loads"]) > 0, response.json()["rooms"]
            )
            # fetch only the light swicthes
            all_active_devices = []
            for room in filtered_rooms:
                loads = []
                for load in room["loads"]:
                    load["room_name"] = room["name"]
                    load["room_id"] = room["id"]
                    loads.append(load)
                all_active_devices.extend(loads)
            # filter only switch devices
            # all_switch_devices = list(
            #     filter(lambda x: x["pin_type"] == pin_number, all_active_devices)
            # )
            self.devices_by_room = {
                device["ID"]: device for device in all_active_devices
            }
            # print(all_active_devices)
            return all_active_devices
        return []

    def get_devices_of_type(self, device_type):
        """Return back all the fans

        @param device_type: "fan" | "switch" | "curtain"
        """
        pin_numbers = ["0"]
        if device_type == "fan":
            pin_numbers = ["3", "4"]  # 4
        elif device_type == "switch":
            pin_numbers = ["1"]
        elif device_type == "curtain":
            pin_numbers = ["7"]
        return list(
            filter(
                lambda x: x["pin_type"] in pin_numbers, self.devices_by_room.values()
            )
        )

    def load_all_parent_devices(self):
        """Load all the parent devices in the account."""
        if self.token is not None:
            response = requests.get(
                f"http://ezcentral.buildtrack.in/btadmin/index.php/restappservice/index/cid/10/rid/{self.role_id}/uid/{self.user_id}/format/json",
                headers={"referer": "https://ezcentral.buildtrack.in/login.html"}
            )
            self.device_parent_ids_map = {
                device["ID"]: device for device in response.json()
            }
            # print(response.json())

    def load_all_devices_raw_details(self):
        """Load all devices raw details."""
        if self.token is not None:
            response = requests.get(
                f"http://ezcentral.buildtrack.in/btadmin/index.php/buildtrackrestappservice/getCatRecordForAssign/format/json?type=11&userid={self.user_id}&roleID={self.role_id}&token={self.token}&recordID=&defineFields=&filterID=&hierarchyFilter=&is_template=0&action=0&is_association=0&recordsonly=1&sync=1",
                headers={"referer": "https://ezcentral.buildtrack.in/login.html"}
            )
            self.device_raw_details_map = {
                device["ID"]: device for device in response.json()
            }
            # print(response.json())

    def get_mac_id_for_device(self, device_id: str):
        """Return back the mac id for the device."""
        if device_id in self.device_parent_ids_map:
            return self.device_parent_ids_map[device_id]["mac_id"]

    def is_device_on_mqtt(self, device_id: str) -> bool:
        """Return back the if the device is connected to the mqtt."""
        try:
            if device_id in self.device_parent_ids_map and (self.device_parent_ids_map[device_id]["product_info"]).strip() != "":
                decoded = json.loads(self.device_parent_ids_map[device_id]["product_info"])
                return not ("mqttState" in decoded and "0" in decoded["mqttState"])
        except:
            return False
        return False

    def get_device_state(self, device_id: str):
        mac_id = self.get_mac_id_for_device(
            self.devices_by_room[device_id]["parentrecordID"]
        )
        pin_number = self.device_raw_details_map[device_id]["pin_number"]
        return self.device_state_manager.fetch_device_state(mac_id, pin_number)

    async def switch_on(self, device_id: str, speed=None):
        """Turn the device on."""

        mac_id = self.get_mac_id_for_device(
            self.devices_by_room[device_id]["parentrecordID"]
        )
        pin_number = self.device_raw_details_map[device_id]["pin_number"]
        self.device_state_manager.switch_on(mac_id, pin_number, speed)

    async def switch_off(self, device_id: str, speed=None):
        """Turn the device off."""
        mac_id = self.get_mac_id_for_device(
            self.devices_by_room[device_id]["parentrecordID"]
        )
        pin_number = self.device_raw_details_map[device_id]["pin_number"]
        self.device_state_manager.switch_off(mac_id, pin_number, speed)

    def open_cover(self, device_id: str):
        mac_id = self.get_mac_id_for_device(
            self.devices_by_room[device_id]["parentrecordID"]
        )
        pin_number = self.device_raw_details_map[device_id]["pin_number"]
        self.device_state_manager.set_cover_state(mac_id, pin_number, state="open")

    def close_cover(self, device_id: str):
        mac_id = self.get_mac_id_for_device(
            self.devices_by_room[device_id]["parentrecordID"]
        )
        pin_number = self.device_raw_details_map[device_id]["pin_number"]
        self.device_state_manager.set_cover_state(mac_id, pin_number, state="close")

    def stop_cover(self, device_id: str):
        mac_id = self.get_mac_id_for_device(
            self.devices_by_room[device_id]["parentrecordID"]
        )
        pin_number = self.device_raw_details_map[device_id]["pin_number"]
        self.device_state_manager.set_cover_state(mac_id, pin_number, state="stop")

    def is_device_on(self, device_id: str) -> bool:
        """Check if the device is on or not."""
        if device_id not in self.devices_by_room.keys():
            return False
        mac_id = self.get_mac_id_for_device(
            self.devices_by_room[device_id]["parentrecordID"]
        )
        pin_number = self.device_raw_details_map[device_id]["pin_number"]
        state = self.device_state_manager.is_device_on(mac_id, pin_number)
        return state

    async def toggle_device(self, device_id: str):
        """Toggle the device state."""
        if self.is_device_on(device_id):
            await self.switch_off(device_id)
        else:
            await self.switch_on(device_id)

    def listen_device_state(self, device_id: str):
        """Listen for device state."""
        mac_id = self.get_mac_id_for_device(
            self.devices_by_room[device_id]["parentrecordID"]
        )

        # print("----------")
        # print(f"{mac_id} {device_id}")
        # check if the device is on MQTT or not
        if self.is_device_on_mqtt(self.devices_by_room[device_id]["parentrecordID"]):
            # print(f"{mac_id} is on MQTT")
            self.device_state_manager.device_mqtt_mac_ids.append(mac_id)
        else:
            # print(f"{mac_id} is on TCP")
            self.device_state_manager.listen_to_tcp_device_status(mac_id)

# 42["event_push","{\"macID\":\"40F5202635A3\",\"event\":\"execute\",\"command\":\"execute\",\"params\":[{\"pin\":\"1\",\"state\":\"close\",\"speed\":\"0\"}],\"passcode\":\"40F5202635A3\",\"to\":\"40F5202635A3\"}"] open | stop
