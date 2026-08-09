import json
import logging
import os
import signal
import threading
import time

import paho.mqtt.client as mqtt
from smbus2 import SMBus

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_KEEPALIVE = 60
MQTT_USERNAME = os.environ.get("MQTT_USER")
MQTT_PASSWORD = os.environ.get("MQTT_PASS")

MQTT_CLIENT_ID = os.environ.get("PREAMP_LED_MQTT_CLIENT_ID", "aswitch-preamp-led")
PREAMP_TRIGGER_STATE_TOPIC = os.environ.get(
    "PREAMP_TRIGGER_STATE_TOPIC", "aswitch/preamp/trigger/state"
)
PREAMP_LED_STATE_TOPIC = os.environ.get("PREAMP_LED_STATE_TOPIC", "aswitch/preamp/led/state")
PREAMP_INPUT_STATE_TOPIC = os.environ.get("PREAMP_INPUT_STATE_TOPIC", "aswitch/preamp/input/state")
PREAMP_LED_RGB_TOPIC = os.environ.get("PREAMP_LED_RGB_TOPIC", "aswitch/preamp/led/rgb")
PREAMP_LED_AVAILABILITY_TOPIC = os.environ.get(
    "PREAMP_LED_AVAILABILITY_TOPIC", "aswitch/preamp/led/availability"
)
TCS34725_I2C_BUS = int(os.environ.get("TCS34725_I2C_BUS", "1"))
TCS34725_I2C_ADDRESS = int(os.environ.get("TCS34725_I2C_ADDRESS", "0x29"), 0)
TCS34725_INTEGRATION_TIME = int(os.environ.get("TCS34725_INTEGRATION_TIME", "0xD6"), 0)
TCS34725_GAIN = int(os.environ.get("TCS34725_GAIN", "0x01"), 0)
PREAMP_LED_SAMPLE_INTERVAL_SECONDS = float(os.environ.get("PREAMP_LED_SAMPLE_INTERVAL_SECONDS", "1"))
PREAMP_LED_OFF_CLEAR_THRESHOLD = int(os.environ.get("PREAMP_LED_OFF_CLEAR_THRESHOLD", "10"))
PREAMP_LED_COLOR_DOMINANCE_RATIO = float(
    os.environ.get("PREAMP_LED_COLOR_DOMINANCE_RATIO", "1.5")
)
PREAMP_INPUT_BLUE_STATE = os.environ.get("PREAMP_INPUT_BLUE_STATE", "input_1")
PREAMP_INPUT_RED_STATE = os.environ.get("PREAMP_INPUT_RED_STATE", "input_2")

TCS34725_COMMAND_BIT = 0x80
TCS34725_ENABLE = 0x00
TCS34725_ATIME = 0x01
TCS34725_CONTROL = 0x0F
TCS34725_ID = 0x12
TCS34725_CDATAL = 0x14
TCS34725_PON = 0x01
TCS34725_AEN = 0x02
TCS34725_EXPECTED_IDS = {0x44, 0x4D}


class Tcs34725:
    def __init__(self, bus_number, address):
        self.bus = SMBus(bus_number)
        self.address = address

    def _write_byte(self, register, value):
        self.bus.write_byte_data(self.address, TCS34725_COMMAND_BIT | register, value)

    def _read_byte(self, register):
        return self.bus.read_byte_data(self.address, TCS34725_COMMAND_BIT | register)

    def start(self):
        sensor_id = self._read_byte(TCS34725_ID)
        if sensor_id not in TCS34725_EXPECTED_IDS:
            raise RuntimeError(f"Unexpected TCS34725 ID: 0x{sensor_id:02X}")
        self._write_byte(TCS34725_ATIME, TCS34725_INTEGRATION_TIME)
        self._write_byte(TCS34725_CONTROL, TCS34725_GAIN)
        self._write_byte(TCS34725_ENABLE, TCS34725_PON)
        time.sleep(0.003)
        self._write_byte(TCS34725_ENABLE, TCS34725_PON | TCS34725_AEN)

    def read(self):
        data = self.bus.read_i2c_block_data(
            self.address, TCS34725_COMMAND_BIT | TCS34725_CDATAL, 8
        )
        clear, red, green, blue = (
            data[index] | (data[index + 1] << 8) for index in range(0, 8, 2)
        )
        return {"clear": clear, "red": red, "green": green, "blue": blue}

    def close(self):
        self.bus.close()


def classify_led(reading):
    if reading["clear"] <= PREAMP_LED_OFF_CLEAR_THRESHOLD:
        return "off"

    red = reading["red"]
    green = reading["green"]
    blue = reading["blue"]
    ratio = PREAMP_LED_COLOR_DOMINANCE_RATIO
    if red >= green * ratio and red >= blue * ratio:
        return "red"
    if blue >= red * ratio and blue >= green * ratio:
        return "blue"
    return "unknown"


def input_for_led_state(led_state):
    return {"blue": PREAMP_INPUT_BLUE_STATE, "red": PREAMP_INPUT_RED_STATE}.get(
        led_state, led_state
    )


class PreampLedMonitor:
    def __init__(self):
        self.logger = logging.getLogger("preamp_led")
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._mqtt_connected = False
        self._trigger_state = None
        self._last_led_state = None
        self._last_input_state = None
        self.sensor = Tcs34725(TCS34725_I2C_BUS, TCS34725_I2C_ADDRESS)
        self.client = self._build_client()

    def _build_client(self):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
        if MQTT_USERNAME:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        client.will_set(PREAMP_LED_AVAILABILITY_TOPIC, "offline", retain=True)
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_message = self.on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        return client

    def _publish(self, topic, payload):
        info = self.client.publish(topic, payload, retain=True)
        self.logger.info("Published %s -> %s (mid=%s)", topic, payload, info.mid)

    def _publish_states(self, led_state, force=False):
        input_state = input_for_led_state(led_state)
        if force or led_state != self._last_led_state:
            self._publish(PREAMP_LED_STATE_TOPIC, led_state)
            self._last_led_state = led_state
        if force or input_state != self._last_input_state:
            self._publish(PREAMP_INPUT_STATE_TOPIC, input_state)
            self._last_input_state = input_state

    def _effective_led_state(self, reading):
        with self._state_lock:
            trigger_state = self._trigger_state
        if trigger_state == "off":
            return "off"
        if trigger_state != "on":
            return "unknown"
        return classify_led(reading)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.logger.info("Connected to MQTT: reason_code=%s", reason_code)
        with self._state_lock:
            self._mqtt_connected = True
        client.subscribe(PREAMP_TRIGGER_STATE_TOPIC)
        client.publish(PREAMP_LED_AVAILABILITY_TOPIC, "online", retain=True)

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        with self._state_lock:
            self._mqtt_connected = False
        if self._stop.is_set():
            self.logger.info("Disconnected from MQTT")
        else:
            self.logger.warning("MQTT disconnected unexpectedly: reason_code=%s", reason_code)

    def on_message(self, client, userdata, message):
        if message.topic != PREAMP_TRIGGER_STATE_TOPIC:
            return
        state = message.payload.decode(errors="ignore").strip().lower()
        if state not in {"on", "off"}:
            self.logger.warning("Ignoring invalid preamp trigger state: %s", state)
            return
        with self._state_lock:
            self._trigger_state = state
        self.logger.info("Preamp trigger state: %s", state)

    def start(self):
        self.sensor.start()
        self.logger.info(
            "Monitoring TCS34725 on I2C bus %s at address 0x%02X",
            TCS34725_I2C_BUS,
            TCS34725_I2C_ADDRESS,
        )
        self.client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
        self.client.loop_start()
        while not self._stop.is_set():
            reading = self.sensor.read()
            self._publish(PREAMP_LED_RGB_TOPIC, json.dumps(reading, separators=(",", ":")))
            self._publish_states(self._effective_led_state(reading))
            self._stop.wait(PREAMP_LED_SAMPLE_INTERVAL_SECONDS)

    def stop(self):
        self._stop.set()
        self.client.disconnect()
        self.client.loop_stop()
        self.sensor.close()


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    monitor = PreampLedMonitor()

    def shutdown(signum=None, frame=None):
        monitor._stop.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        monitor.start()
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
