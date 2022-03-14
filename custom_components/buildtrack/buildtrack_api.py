"""This is wrapper class for interacting with buldtrack server."""
import json
import threading

import requests
import websocket


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class BuildTrackDeviceManager(metaclass=Singleton):
    """This is class which maintains the state of all buildtrack devices."""

    # mac_id_wise_state: TypedDict = {}
    # websocket: websocket.WebSocketApp = None
    # wst: object = None
    is_websocket_connected = False
    pending_listening_devices = set()

    def __init__(self, user_id) -> None:
        """Initialize the Build Track State Manager."""
        self.user_id = user_id
        self.mac_id_wise_state: dict = {}
        self.websocket_connection_connection = None
        self.wst = None
        self.connect_to_buildtrack_server()

    def listen_to_device_status(self, mac_id):
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
                print("Exception while registering device listener for " + mac_id)
                print(ex)

    def manual_device_state_update(self, mac_id, pin_number, state: bool):
        """Update the device status until the websocket response arrives manually."""
        if mac_id in self.mac_id_wise_state:
            self.mac_id_wise_state[mac_id][f"{pin_number}"]["state"] = 1 if state else 0

    def register_all_devices_listeners(self):
        """Register the listeners for all the devices upon new connection."""
        for device_mac in self.mac_id_wise_state:
            self.listen_to_device_status(device_mac)

    def register_pending_devices_listeners(self):
        """Register the listeners for the pending devices upon new connection."""
        tmp_list = self.pending_listening_devices.copy()
        self.pending_listening_devices.clear()
        for device_mac in tmp_list:
            self.listen_to_device_status(device_mac)

    def connect_to_buildtrack_server(self):
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
        # return (
        #     False
        #     if f"{pin_number}" not in self.mac_id_wise_state[mac_id]
        #     or self.mac_id_wise_state[mac_id][f"{pin_number}"] == 0
        #     else True
        # )
        return not (
            mac_id not in self.mac_id_wise_state or
            f"{pin_number}" not in self.mac_id_wise_state[mac_id]
            or self.mac_id_wise_state[mac_id][f"{pin_number}"]["state"] == 0
        )

    def on_message(self, websocket_con, message: str):
        """Process the input message over websocket."""
        if message == "40":
            self.is_websocket_connected = True
            self.register_pending_devices_listeners()

        actual_data = None
        if message.startswith("42"):
            actual_data = message[2:]
        if actual_data is not None:
            decoded_message = json.loads(actual_data)
            if decoded_message[0] == "status":
                self.update_switch_state(decoded_message[1])

    def update_switch_state(self, decoded_message):
        """Update the switch state on the buildtrack server."""
        if decoded_message["command"] == "status":
            if decoded_message["uid"] not in self.mac_id_wise_state:
                self.mac_id_wise_state[decoded_message["uid"]] = {}
            for index, item in enumerate(decoded_message["pin"]):
                if isinstance(item, dict):
                    self.mac_id_wise_state[decoded_message["uid"]][f"{index+1}"] = {
                        "state": int(item["state"]),
                        "speed": int(item["speed"])
                    }
                else:
                    self.mac_id_wise_state[decoded_message["uid"]][f"{index + 1}"] = {"state": int(
                        item
                    )
                    }

    def switch_on(self, mac_id, pin_number, speed=None):
        param = {"pin": pin_number, "state": "on"}
        if speed is not None:
            param["speed "] = speed
        message = json.dumps(
            [
                "event_push",
                json.dumps(
                    {
                        "macID": mac_id,
                        "event": "execute",
                        "command": "execute",
                        "params": [param],
                        "passcode": mac_id,
                        "to": mac_id,
                    }
                ),
            ]
        )
        self.websocket_connection.send("42" + message)
        self.manual_device_state_update(mac_id, pin_number, True)

    def switch_off(self, mac_id, pin_number, speed=None):
        param = {"pin": pin_number, "state": "off"}
        if speed is not None:
            param["speed "] = speed
        message = json.dumps(
            [
                "event_push",
                json.dumps(
                    {
                        "macID": mac_id,
                        "event": "execute",
                        "command": "execute",
                        "params": [param],
                        "passcode": mac_id,
                        "to": mac_id,
                    }
                ),
            ]
        )
        self.websocket_connection.send("42" + message)
        self.manual_device_state_update(mac_id, pin_number, False)

    @classmethod
    def on_error(self, websocket_con, error):
        """Handle websocket error."""
        print(error)

    def on_close(self, websocket_con, close_status_code, close_msg):
        """Handle websocket closed."""
        print("### closed ###")
        self.is_websocket_connected = False
        self.connect_to_buildtrack_server()

    def on_open(self, websocket_con):
        """Handle websocket connection open."""
        print("Connected to buildtrack server....")
        websocket_con.send(f'42["login","{self.user_id}"]')
        self.register_all_devices_listeners()


class BuildTrackAPI(metaclass=Singleton):
    """This is the wrapper class to interact with the Build Track Server."""

    def __init__(self) -> None:
        """Initialize the API class."""
        self.username = None
        self.password = None
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

    def authenticate_user(self) -> bool:
        """Authenticate the user."""
        try:
            response = requests.post(
                "http://ezcentral.buildtrack.in/btadmin/index.php/commonrestappservice/login/format/json",
                headers={"content-type": "application/x-www-form-urlencoded"},
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
                self.device_state_manager = BuildTrackDeviceManager(data["userid"])
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

        if self.token is not None:
            response = requests.get(
                f"http://ezcentral.buildtrack.in/btadmin/index.php/restappservice/getRoomPinDetails/userid/{self.user_id}/roleID/{self.role_id}/token/{self.token}/format/json"
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
            return all_active_devices
        return []

    def get_devices_of_type(self, device_type):
        """Return back all the fans

        @param device_type: "fan" | "switch" | "curtain"
        """
        pin_number = "0"
        if device_type == "fan":
            pin_number = "4"
        elif device_type == "switch":
            pin_number = "1"
        elif device_type == "curtain":
            pin_number = "7"
        return list(
            filter(lambda x: x["pin_type"] == pin_number, self.devices_by_room.values())
        )

    def load_all_parent_devices(self):
        """Load all the parent devices in the account."""
        if self.token is not None:
            response = requests.get(
                f"http://ezcentral.buildtrack.in/btadmin/index.php/restappservice/index/cid/10/rid/{self.role_id}/uid/{self.user_id}/format/json"
            )
            self.device_parent_ids_map = {
                device["ID"]: device for device in response.json()
            }

    def load_all_devices_raw_details(self):
        """Load all devices raw details."""
        if self.token is not None:
            response = requests.get(
                f"http://ezcentral.buildtrack.in/btadmin/index.php/buildtrackrestappservice/getCatRecordForAssign/format/json?type=11&userid={self.user_id}&roleID={self.role_id}&token={self.token}&recordID=&defineFields=&filterID=&hierarchyFilter=&is_template=0&action=0&is_association=0&recordsonly=1&sync=1"
            )
            self.device_raw_details_map = {
                device["ID"]: device for device in response.json()
            }

    def get_mac_id_for_device(self, device_id: str):
        """Return back the mac id for the device."""
        if device_id in self.device_parent_ids_map:
            return self.device_parent_ids_map[device_id]["mac_id"]

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
        self.device_state_manager.listen_to_device_status(mac_id)
