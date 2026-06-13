import logging
import os
import signal
import subprocess
import threading

import paho.mqtt.client as mqtt

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_KEEPALIVE = 60
MQTT_USERNAME = os.environ.get("MQTT_USER")
MQTT_PASSWORD = os.environ.get("MQTT_PASS")

USB_DEVICE_ID = os.environ.get("DAC_USB_ID", "152a:889b").lower()
USB_MATCH_TEXT = os.environ.get("DAC_MATCH_TEXT", "Fosi Audio ZD3").lower()
POLL_INTERVAL_SECONDS = float(os.environ.get("DAC_POLL_INTERVAL_SECONDS", "5.0"))
MQTT_CLIENT_ID = os.environ.get("DAC_MQTT_CLIENT_ID", "aswitch-dac-status")

DAC_STATE_TOPIC = os.environ.get("DAC_STATE_TOPIC", "aswitch/dac/zd3/state")
DAC_DETAILS_TOPIC = os.environ.get("DAC_DETAILS_TOPIC", "aswitch/dac/zd3/details")
DAC_AVAILABILITY_TOPIC = os.environ.get("DAC_AVAILABILITY_TOPIC", "aswitch/dac/zd3/availability")


def normalize_lines(output):
    return [line.strip() for line in output.splitlines() if line.strip()]


def detect_dac():
    result = subprocess.run(
        ["lsusb"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "lsusb failed")

    lines = normalize_lines(result.stdout)
    for line in lines:
        line_lower = line.lower()
        if f"id {USB_DEVICE_ID}" in line_lower or USB_MATCH_TEXT in line_lower:
            return True, line
    return False, ""


class DacStatusPublisher:
    def __init__(self):
        self.logger = logging.getLogger("dac_status")
        self._stop = threading.Event()
        self.last_state = None
        self.last_details = None
        self.client = self._build_client()

    def _build_client(self):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
        if MQTT_USERNAME:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        client.will_set(DAC_AVAILABILITY_TOPIC, "offline", retain=True)
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        return client

    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.logger.info("Connected to MQTT: reason_code=%s", reason_code)
        self.publish_availability("online")

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        if self._stop.is_set():
            self.logger.info("Disconnected from MQTT")
            return
        self.logger.warning("MQTT disconnected: reason_code=%s", reason_code)

    def publish_availability(self, value):
        self.client.publish(DAC_AVAILABILITY_TOPIC, value, retain=True)

    def publish_state(self, connected, details):
        state = "connected" if connected else "disconnected"
        if state != self.last_state:
            self.client.publish(DAC_STATE_TOPIC, state, retain=True)
            self.logger.info("Published %s -> %s", DAC_STATE_TOPIC, state)
            self.last_state = state

        normalized_details = details if connected else ""
        if normalized_details != self.last_details:
            self.client.publish(DAC_DETAILS_TOPIC, normalized_details, retain=True)
            if connected:
                self.logger.info("Published %s -> %s", DAC_DETAILS_TOPIC, normalized_details)
            self.last_details = normalized_details

    def run(self):
        self.client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
        self.client.loop_start()
        self.logger.info(
            "Watching DAC via lsusb (id=%s, text=%s) every %.1fs",
            USB_DEVICE_ID,
            USB_MATCH_TEXT,
            POLL_INTERVAL_SECONDS,
        )

        try:
            while not self._stop.is_set():
                try:
                    connected, details = detect_dac()
                    self.publish_state(connected, details)
                except Exception:
                    self.logger.exception("DAC detection failed")
                self._stop.wait(POLL_INTERVAL_SECONDS)
        finally:
            self.publish_availability("offline")
            self.client.loop_stop()
            self.client.disconnect()

    def stop(self, signum=None, frame=None):
        self._stop.set()


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = DacStatusPublisher()
    signal.signal(signal.SIGINT, app.stop)
    signal.signal(signal.SIGTERM, app.stop)
    app.run()


if __name__ == "__main__":
    main()
