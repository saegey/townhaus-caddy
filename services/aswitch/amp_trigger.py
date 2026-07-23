import logging
import os
import signal

import paho.mqtt.client as mqtt
import RPi.GPIO as GPIO

TRIGGER_PIN = int(os.environ.get("AMP_TRIGGER_GPIO", "27"))

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_KEEPALIVE = 60
MQTT_USERNAME = os.environ.get("MQTT_USER")
MQTT_PASSWORD = os.environ.get("MQTT_PASS")

TRIGGER_COMMAND_TOPIC = os.environ.get("AMP_TRIGGER_COMMAND_TOPIC", "pi-cam/trigger")
TRIGGER_STATE_TOPIC = os.environ.get("AMP_TRIGGER_STATE_TOPIC", "pi-cam/trigger/state")
AVAILABILITY_TOPIC = os.environ.get("AMP_TRIGGER_AVAILABILITY_TOPIC", "pi-cam/availability")

# The Tongling / JQC-3FF relay is active high.
TRIGGER_ON = GPIO.HIGH
TRIGGER_OFF = GPIO.LOW


logger = logging.getLogger("amp_trigger")


def normalize_payload(payload):
    return payload.decode(errors="ignore").strip().lower()


def publish_state(client, topic, state):
    info = client.publish(topic, state, retain=True)
    logger.info("Published %s -> %s (mid=%s)", topic, state, info.mid)


def current_trigger_state():
    return "on" if GPIO.input(TRIGGER_PIN) == TRIGGER_ON else "off"


def set_trigger(client, state, publish=True):
    if state not in {"on", "off"}:
        logger.warning("Ignoring invalid trigger command: %s", state)
        return

    current = current_trigger_state()
    if current == state:
        logger.info("Trigger already %s", state)
        if publish:
            publish_state(client, TRIGGER_STATE_TOPIC, current)
        return

    GPIO.output(TRIGGER_PIN, TRIGGER_ON if state == "on" else TRIGGER_OFF)
    new_state = current_trigger_state()
    logger.info("Trigger changed: %s -> %s", current, new_state)
    if publish:
        publish_state(client, TRIGGER_STATE_TOPIC, new_state)


def on_connect(client, userdata, flags, reason_code, properties):
    logger.info("Connected to MQTT: reason_code=%s", reason_code)
    client.subscribe(TRIGGER_COMMAND_TOPIC)
    client.publish(AVAILABILITY_TOPIC, "online", retain=True)
    publish_state(client, TRIGGER_STATE_TOPIC, current_trigger_state())


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    if reason_code.value == 0:
        logger.info("Disconnected from MQTT")
    else:
        logger.warning("MQTT disconnected unexpectedly: reason_code=%s", reason_code)


def on_message(client, userdata, msg):
    payload = normalize_payload(msg.payload)
    logger.info("Incoming %s -> %s", msg.topic, payload)
    if msg.topic == TRIGGER_COMMAND_TOPIC:
        set_trigger(client, payload)


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(TRIGGER_PIN, GPIO.OUT, initial=TRIGGER_OFF)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.will_set(AVAILABILITY_TOPIC, "offline", retain=True)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    def shutdown(signum=None, frame=None):
        logger.info("Shutting down")
        client.disconnect()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
        client.loop_forever()
    finally:
        GPIO.output(TRIGGER_PIN, TRIGGER_OFF)
        logger.info("Applied safe default: trigger=off")
        GPIO.cleanup()


if __name__ == "__main__":
    main()
