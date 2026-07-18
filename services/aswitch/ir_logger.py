import json
import logging
import os
import signal
import threading
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
import pigpio

from preamp_ir_codes import PREAMP_IR_ALIASES, PREAMP_IR_FINGERPRINTS, PREAMP_IR_PULSES

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_KEEPALIVE = 60
MQTT_USERNAME = os.environ.get("MQTT_USER")
MQTT_PASSWORD = os.environ.get("MQTT_PASS")

MQTT_CLIENT_ID = os.environ.get("IR_MQTT_CLIENT_ID", "aswitch-ir-logger")
IR_GPIO = int(os.environ.get("IR_GPIO", "17"))
IR_TX_GPIO = int(os.environ.get("IR_TX_GPIO", "18"))
IR_FRAME_GAP_US = int(os.environ.get("IR_FRAME_GAP_US", "15000"))
IR_GLITCH_FILTER_US = int(os.environ.get("IR_GLITCH_FILTER_US", "100"))

IR_TOPIC_RECEIVED = os.environ.get("IR_TOPIC_RECEIVED", "aswitch/ir/received")
IR_TOPIC_AVAILABILITY = os.environ.get("IR_TOPIC_AVAILABILITY", "aswitch/ir/availability")
IR_TOPIC_SEND = os.environ.get("IR_TOPIC_SEND", "aswitch/ir/send")
IR_TOPIC_SENT = os.environ.get("IR_TOPIC_SENT", "aswitch/ir/sent")
IR_TX_FREQUENCY_HZ = int(os.environ.get("IR_TX_FREQUENCY_HZ", "38000"))
IR_TX_REPEAT_COUNT = int(os.environ.get("IR_TX_REPEAT_COUNT", "1"))

SHORT_FRAME_MAX_PULSES = 8
BIT_ONE_THRESHOLD_US = 1000
MIN_FULL_FRAME_PULSES = 66
FINGERPRINT_TO_BUTTON = {value: key for key, value in PREAMP_IR_FINGERPRINTS.items()}


def classify_frame(pulses_us):
    if len(pulses_us) <= SHORT_FRAME_MAX_PULSES:
        return "short"
    return "full"


def derive_fingerprint(pulses_us):
    if len(pulses_us) < MIN_FULL_FRAME_PULSES:
        return None

    data = pulses_us[2:]
    bits = []
    for i in range(0, min(len(data) - 1, 64), 2):
        space = data[i + 1]
        bits.append("1" if space > BIT_ONE_THRESHOLD_US else "0")

    if len(bits) != 32:
        return None

    bit_string = "".join(bits)
    return {
        "bits": bit_string,
        "hex": f"0x{int(bit_string, 2):08X}",
        "button": FINGERPRINT_TO_BUTTON.get(bit_string),
    }


def normalize_command(command):
    normalized = command.strip().lower()
    return PREAMP_IR_ALIASES.get(normalized, normalized)


def build_mark_pulses(gpio, frequency_hz, duration_us):
    if duration_us <= 0:
        return []

    gpio_mask = 1 << gpio
    cycle_us = 1_000_000 / frequency_hz
    half_cycle_us = cycle_us / 2
    pulses = []
    elapsed_us = 0.0
    high = True

    while elapsed_us < duration_us:
        remaining_us = duration_us - elapsed_us
        pulse_us = max(1, int(round(min(half_cycle_us, remaining_us))))
        if high:
            pulses.append(pigpio.pulse(gpio_mask, 0, pulse_us))
        else:
            pulses.append(pigpio.pulse(0, gpio_mask, pulse_us))
        elapsed_us += pulse_us
        high = not high

    if pulses and pulses[-1].gpio_on:
        pulses.append(pigpio.pulse(0, gpio_mask, 1))
    return pulses


def build_frame_wave(gpio, frequency_hz, pulses_us):
    gpio_mask = 1 << gpio
    wave = []
    for index, duration_us in enumerate(pulses_us):
        if index % 2 == 0:
            wave.extend(build_mark_pulses(gpio, frequency_hz, duration_us))
        else:
            wave.append(pigpio.pulse(0, gpio_mask, duration_us))
    wave.append(pigpio.pulse(0, gpio_mask, 1000))
    return wave


class IrLogger:
    def __init__(self):
        self.logger = logging.getLogger("ir_logger")
        self._stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._tx_lock = threading.Lock()
        self._current_pulses = []
        self._last_tick = None
        self._last_level = None
        self.client = self._build_client()
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError("Unable to connect to pigpiod")
        self._callback = None

    def _build_client(self):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
        if MQTT_USERNAME:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        client.will_set(IR_TOPIC_AVAILABILITY, "offline", retain=True)
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        return client

    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.logger.info("Connected to MQTT: reason_code=%s", reason_code)
        client.publish(IR_TOPIC_AVAILABILITY, "online", retain=True)
        client.subscribe(IR_TOPIC_SEND)
        self.logger.info("Subscribed to command topic: %s", IR_TOPIC_SEND)

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        if self._stop.is_set():
            self.logger.info("Disconnected from MQTT")
            return
        self.logger.warning("MQTT disconnected: reason_code=%s", reason_code)

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode(errors="ignore").strip()
        self.logger.info("Command %s -> %s", msg.topic, payload)
        if msg.topic == IR_TOPIC_SEND:
            self._send_command(payload)

    def _publish_frame(self, pulses_us):
        if not pulses_us:
            return

        frame_type = classify_frame(pulses_us)
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "gpio": IR_GPIO,
            "tx_gpio": IR_TX_GPIO,
            "idle_gap_us": IR_FRAME_GAP_US,
            "frame_type": frame_type,
            "pulses_us": pulses_us,
        }
        fingerprint = derive_fingerprint(pulses_us)
        if fingerprint is not None:
            payload["fingerprint_bits"] = fingerprint["bits"]
            payload["fingerprint_hex"] = fingerprint["hex"]
            payload["button"] = fingerprint["button"]
        self.client.publish(IR_TOPIC_RECEIVED, json.dumps(payload), retain=False)
        self.logger.info(
            "Published IR %s frame with %s pulses%s",
            frame_type,
            len(pulses_us),
            f" ({fingerprint['button']})" if fingerprint and fingerprint["button"] else "",
        )

    def _publish_sent(self, command, fingerprint_hex):
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "button": command,
            "fingerprint_hex": fingerprint_hex,
            "tx_gpio": IR_TX_GPIO,
            "tx_frequency_hz": IR_TX_FREQUENCY_HZ,
            "repeat_count": IR_TX_REPEAT_COUNT,
        }
        self.client.publish(IR_TOPIC_SENT, json.dumps(payload), retain=False)

    def _send_command(self, command):
        normalized = normalize_command(command)
        pulses_us = PREAMP_IR_PULSES.get(normalized)
        fingerprint_bits = PREAMP_IR_FINGERPRINTS.get(normalized)
        if pulses_us is None or fingerprint_bits is None:
            self.logger.warning("Ignoring unknown IR command: %s", command)
            return

        fingerprint_hex = f"0x{int(fingerprint_bits, 2):08X}"
        wave = build_frame_wave(IR_TX_GPIO, IR_TX_FREQUENCY_HZ, pulses_us)

        with self._tx_lock:
            self.pi.wave_tx_stop()
            self.pi.wave_clear()
            self.pi.wave_add_generic(wave)
            wave_id = self.pi.wave_create()
            if wave_id < 0:
                self.logger.error("Failed to create IR wave for %s", normalized)
                return

            try:
                for _ in range(IR_TX_REPEAT_COUNT):
                    self.pi.wave_send_once(wave_id)
                    while self.pi.wave_tx_busy():
                        if self._stop.wait(0.01):
                            break
                    if self._stop.is_set():
                        break
                    self._stop.wait(0.04)
            finally:
                self.pi.wave_delete(wave_id)

        self.logger.info(
            "Sent IR command: %s (%s) x%s",
            normalized,
            fingerprint_hex,
            IR_TX_REPEAT_COUNT,
        )
        self._publish_sent(normalized, fingerprint_hex)

    def _finish_frame_locked(self):
        if not self._current_pulses:
            return
        pulses_us = self._current_pulses
        self._current_pulses = []
        self._publish_frame(pulses_us)

    def _on_edge(self, gpio, level, tick):
        if level == pigpio.TIMEOUT:
            return

        with self._frame_lock:
            if self._last_tick is None:
                self._last_tick = tick
                self._last_level = level
                return

            duration = pigpio.tickDiff(self._last_tick, tick)
            if duration >= IR_FRAME_GAP_US:
                self._finish_frame_locked()
            else:
                self._current_pulses.append(duration)

            self._last_tick = tick
            self._last_level = level

    def run(self):
        self.pi.set_mode(IR_GPIO, pigpio.INPUT)
        self.pi.set_mode(IR_TX_GPIO, pigpio.OUTPUT)
        self.pi.write(IR_TX_GPIO, 0)
        self.pi.set_pull_up_down(IR_GPIO, pigpio.PUD_UP)
        self.pi.set_glitch_filter(IR_GPIO, IR_GLITCH_FILTER_US)
        self._callback = self.pi.callback(IR_GPIO, pigpio.EITHER_EDGE, self._on_edge)

        self.client.on_message = self.on_message
        self.client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
        self.client.loop_start()
        self.logger.info(
            "Logging IR frames on GPIO%s and transmitting on GPIO%s at %sHz",
            IR_GPIO,
            IR_TX_GPIO,
            IR_TX_FREQUENCY_HZ,
        )
        self.logger.info(
            "Frame gap %sus, glitch filter %sus, command topic %s",
            IR_FRAME_GAP_US,
            IR_GLITCH_FILTER_US,
            IR_TOPIC_SEND,
        )

        try:
            while not self._stop.wait(0.5):
                pass
        finally:
            with self._frame_lock:
                self._finish_frame_locked()
            self.client.publish(IR_TOPIC_AVAILABILITY, "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()
            if self._callback is not None:
                self._callback.cancel()
            self.pi.set_glitch_filter(IR_GPIO, 0)
            self.pi.write(IR_TX_GPIO, 0)
            self.pi.stop()

    def stop(self, signum=None, frame=None):
        self._stop.set()


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = IrLogger()
    signal.signal(signal.SIGINT, app.stop)
    signal.signal(signal.SIGTERM, app.stop)
    app.run()


if __name__ == "__main__":
    main()
