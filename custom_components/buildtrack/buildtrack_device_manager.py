from .common import Singleton, mqtt_website_certificate
import paho.mqtt.client as mqtt
import json
import threading
import websocket
import os
import string
import random


class BuildTrackDeviceManager(metaclass=Singleton):
    """This is class which maintains the state of all buildtrack devices."""

    # mac_id_wise_state: TypedDict = {}
    # websocket: websocket.WebSocketApp = None
    # wst: object = None
    is_websocket_connected = False
    is_mqtt_connected = False
    pending_listening_devices = set()
    device_mqtt_mac_ids = []
    mqtt_client = None
    mqtt_username = None
    mqtt_password = None

    def __init__(self, user_id, mqtt_username, mqtt_password) -> None:
        """Initialize the Build Track State Manager."""
        self.user_id = user_id
        self.mqtt_username = mqtt_username
        self.mqtt_password = mqtt_password
        self.mac_id_wise_state: dict = {}
        self.websocket_connection = None
        self.wst = None
        self.mqtt_thread = None
        self.connect_to_buildtrack_tcp_server()
        self.connect_to_buildtrack_mqtt_server()
    @staticmethod
    def generateRandomClientName(N=16):
        return ''.join(random.choices(string.ascii_uppercase +
                                      string.digits, k=N))

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
                print("Exception while registering device listener for " + mac_id)
                print(ex)

    def manual_device_state_update(self, mac_id, pin_number, state: bool):
        """Update the device status until the websocket response arrives manually."""
        if mac_id in self.mac_id_wise_state:
            # print(self.mac_id_wise_state[mac_id])
            # print(str(pin_number))
            # print(state)

            self.mac_id_wise_state[mac_id][f"{pin_number}"]["state"] = 1 if state else 0

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

    def connect_to_buildtrack_mqtt_server(self):
        self.mqtt_client = mqtt.Client(client_id=BuildTrackDeviceManager.generateRandomClientName())

        # The callback for when the client receives a CONNACK response from the server.
        def on_connect(client, userdata, flags, rc):
            print("Buildtrack MQTT Server connected with result code " + str(rc))
            # Subscribing in on_connect() means that if we lose the connection and
            # reconnect then subscriptions will be renewed.
            
            # this is mainly to support websocket via mqtt
            client.publish("WillMsg", payload="Connection Closed abnormally..!")


            self.is_mqtt_connected = True
            for mac_id in self.device_mqtt_mac_ids:
                client.subscribe(mac_id + "/status")

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
            topic = str(msg.topic)
            message = str(msg.payload.decode("utf-8"))
            decoded_message = json.loads(message)
            print(decoded_message)
            self.update_switch_state(decoded_message)

        def on_log(client, userdata, level, buf):
            print("log: ", buf)

        def on_disconnect(client, userdata, rc):
            print("Buildtrack MQTT Server Disconnected")
            self.is_mqtt_connected = False
            self.connect_to_buildtrack_mqtt_server()

        self.mqtt_client.on_connect = on_connect
        self.mqtt_client.on_message = on_message
        # self.mqtt_client.on_log = on_log
        self.mqtt_client.disconnect_callback = on_disconnect
        self.mqtt_client.username_pw_set(self.mqtt_username, self.mqtt_password)
        print(f"CWD : {os.getcwd()}")
        # TODO - Enable this for development
        # self.mqtt_client.tls_set(ca_certs=f"{os.getcwd()}/config/custom_components/buildtrack/ms.buildtrack.in.cer")

        # TODO - Enable this for production before pushing the code
        # self.mqtt_client.tls_set(ca_certs="/root/config/custom_components/buildtrack/ms.buildtrack.in.cer")

        cert_file = open("mqtt_website_certificate.cer", "w")
        cert_file.write(mqtt_website_certificate)
        cert_file.close()
        self.mqtt_client.tls_set(ca_certs="mqtt_website_certificate.cer")

        self.mqtt_client.tls_insecure_set(True)
        self.mqtt_client.connect("ms.buildtrack.in", 1899, 60)
        # self.mqtt_client.loop_forever()
        self.mqtt_thread = threading.Thread(
            target=self.mqtt_client.loop_forever,
            kwargs={"timeout": 20},
        )
        self.mqtt_thread.daemon = True
        self.mqtt_thread.start()

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

    def fetch_device_state(self, mac_id, pin_number):
        """return the device state object"""
        if (
                mac_id not in self.mac_id_wise_state
                or f"{pin_number}" not in self.mac_id_wise_state[mac_id]
        ):
            return {"state": 0, "speed": 0}
        else:
            return self.mac_id_wise_state[mac_id][f"{pin_number}"]

    def update_switch_state(self, decoded_message):
        """Update the switch state on the buildtrack server."""
        # print(decoded_message)
        if decoded_message["command"] == "status":
            if decoded_message["uid"] not in self.mac_id_wise_state:
                # if decoded_message["uid"] == "40F5200DCF2D":
                # print(decoded_message["uid"] + " not in mac_id_wise_state")
                self.mac_id_wise_state[decoded_message["uid"]] = {}
            # if decoded_message["uid"] == "40F5200DCF2D":
            # print(decoded_message)
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

    def switch_on(self, mac_id, pin_number, speed=None):
        """Switch on the device"""
        print(f"Switching on {mac_id} with speed={speed}")
        param = {"pin": pin_number, "state": "on"}
        if speed is not None:
            param["speed"] = str(speed)
        command = {
            "macID": mac_id,
            "event": "execute",
            "command": "execute",
            "params": [param],
            "passcode": mac_id,
            "to": mac_id,
        }
        if mac_id in self.device_mqtt_mac_ids:
            self.mqtt_client.publish(f"{mac_id}/execute", payload=json.dumps(
                command
            ))
        else:
            message = json.dumps(
                [
                    "event_push",
                    json.dumps(
                        command
                    ),
                ]
            )
            self.websocket_connection.send("42" + message)
        self.manual_device_state_update(mac_id, pin_number, True)

    def switch_off(self, mac_id, pin_number, speed=None):
        """Switch Off device"""
        print(f"Switching off {mac_id}")
        param = {"pin": pin_number, "state": "off"}
        if speed is not None:
            param["speed"] = str(speed)
        command = {
            "macID": mac_id,
            "event": "execute",
            "command": "execute",
            "params": [param],
            "passcode": mac_id,
            "to": mac_id,
        }
        if mac_id in self.device_mqtt_mac_ids:
            # print("MQTT Device")
            self.mqtt_client.publish(f"{mac_id}/execute", payload=json.dumps(
                command
            ))
        else:
            # print("TCP Device")
            message = json.dumps(
                [
                    "event_push",
                    json.dumps(
                        command
                    ),
                ]
            )
            self.websocket_connection.send("42" + message)
        self.manual_device_state_update(mac_id, pin_number, False)

    def set_cover_state(self, mac_id, pin_number, state="open"):
        """Set Cover state"""
        param = {"pin": pin_number, "state": state, "speed": "0"}

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
        self.connect_to_buildtrack_tcp_server()

    def on_open(self, websocket_con):
        """Handle websocket connection open."""
        print("Connected to buildtrack server....")
        websocket_con.send(f'42["login","{self.user_id}"]')
        self.register_all_tcp_devices_listeners()
