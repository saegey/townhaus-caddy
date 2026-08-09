import logging
import os
import signal
import threading

import paho.mqtt.client as mqtt
import pigpio

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_KEEPALIVE = 60
MQTT_USERNAME = os.environ.get("MQTT_USER")
MQTT_PASSWORD = os.environ.get("MQTT_PASS")

MQTT_CLIENT_ID = os.environ.get("PREAMP_TRIGGER_MQTT_CLIENT_ID", "aswitch-preamp-trigger")
PREAMP_TRIGGER_GPIO = int(os.environ.get("PREAMP_TRIGGER_GPIO", "23"))
PREAMP_TRIGGER_GLITCH_FILTER_US = int(
    os.environ.get("PREAMP_TRIGGER_GLITCH_FILTER_US", "20000")
)
PREAMP_TRIGGER_STATE_TOPIC = os.environ.get(
    "PREAMP_TRIGGER_STATE_TOPIC", "aswitch/preamp/trigger/state"
)
PREAMP_TRIGGER_AVAILABILITY_TOPIC = os.environ.get(
    "PREAMP_TRIGGER_AVAILABILITY_TOPIC", "aswitch/preamp/trigger/availability"
)


class PreampTriggerMonitor:
    def __init__(self):
        self.logger = logging.getLogger("preamp_trigger")
        self._state_lock = threading.Lock()
        self._mqtt_connected = False
        self._state = None
        self._stop = threading.Event()
        self.client = self._build_client()
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError("Unable to connect to pigpiod")
        self._callback = None

    def _build_client(self):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
        if MQTT_USERNAME:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        client.will_set(PREAMP_TRIGGER_AVAILABILITY_TOPIC, "offline", retain=True)
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        return client

    def _read_state(self):
        return "on" if self.pi.read(PREAMP_TRIGGER_GPIO) == 0 else "off"

    def _publish_state(self, state):
        info = self.client.publish(PREAMP_TRIGGER_STATE_TOPIC, state, retain=True)
        self.logger.info("Published %s -> %s (mid=%s)", PREAMP_TRIGGER_STATE_TOPIC, state, info.mid)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.logger.info("Connected to MQTT: reason_code=%s", reason_code)
        with self._state_lock:
            self._mqtt_connected = True
            self._state = self._read_state()
            state = self._state
        client.publish(PREAMP_TRIGGER_AVAILABILITY_TOPIC, "online", retain=True)
        self._publish_state(state)

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        with self._state_lock:
            self._mqtt_connected = False
        if self._stop.is_set():
            self.logger.info("Disconnected from MQTT")
        else:
            self.logger.warning("MQTT disconnected unexpectedly: reason_code=%s", reason_code)

    def _on_edge(self, gpio, level, tick):
        if level == pigpio.TIMEOUT:
            return

        state = "on" if level == 0 else "off"
        with self._state_lock:
            changed = state != self._state
            self._state = state
            mqtt_connected = self._mqtt_connected

        if changed:
            self.logger.info("Preamp trigger changed: %s", state)
            if mqtt_connected:
                self._publish_state(state)

    def start(self):
        self.pi.set_mode(PREAMP_TRIGGER_GPIO, pigpio.INPUT)
        self.pi.set_pull_up_down(PREAMP_TRIGGER_GPIO, pigpio.PUD_UP)
        self.pi.set_glitch_filter(PREAMP_TRIGGER_GPIO, PREAMP_TRIGGER_GLITCH_FILTER_US)
        with self._state_lock:
            self._state = self._read_state()
        self._callback = self.pi.callback(PREAMP_TRIGGER_GPIO, pigpio.EITHER_EDGE, self._on_edge)
        self.logger.info(
            "Monitoring preamp trigger on GPIO%s (initial state: %s)",
            PREAMP_TRIGGER_GPIO,
            self._state,
        )
        self.client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
        self.client.loop_forever()

    def stop(self):
        self._stop.set()
        if self._callback is not None:
            self._callback.cancel()
        self.pi.set_glitch_filter(PREAMP_TRIGGER_GPIO, 0)
        self.client.disconnect()
        self.pi.stop()


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    monitor = PreampTriggerMonitor()

    def shutdown(signum=None, frame=None):
        monitor._stop.set()
        monitor.client.disconnect()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        monitor.start()
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
