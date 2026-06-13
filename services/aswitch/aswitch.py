import logging
import os
import signal

import paho.mqtt.client as mqtt
import RPi.GPIO as GPIO

AUDIO_PIN = 17
TRIGGER_PIN = 27

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60
MQTT_USERNAME = os.environ.get("MQTT_USER")
MQTT_PASSWORD = os.environ.get("MQTT_PASS")

AUDIO_COMMAND_TOPIC = "aswitch/audio"
AUDIO_STATE_TOPIC = "aswitch/audio/state"
TRIGGER_COMMAND_TOPIC = "aswitch/trigger"
TRIGGER_STATE_TOPIC = "aswitch/trigger/state"
AVAILABILITY_TOPIC = "aswitch/availability"

# Relay boards are active opposite from the original assumption.
AUDIO_DAC = GPIO.HIGH
AUDIO_MIXER = GPIO.LOW

TRIGGER_ON = GPIO.HIGH
TRIGGER_OFF = GPIO.LOW


logger = logging.getLogger("aswitch")


def normalize_payload(payload):
    return payload.decode(errors="ignore").strip().lower()


def publish_state(client, topic, state):
    info = client.publish(topic, state, retain=True)
    logger.info("Published %s -> %s (mid=%s)", topic, state, info.mid)


def current_audio_state():
    return "dac" if GPIO.input(AUDIO_PIN) == AUDIO_DAC else "mixer"


def current_trigger_state():
    return "on" if GPIO.input(TRIGGER_PIN) == TRIGGER_ON else "off"


def set_audio(client, source, publish=True):
    if source not in {"dac", "mixer"}:
        logger.warning("Ignoring invalid audio command: %s", source)
        return

    current = current_audio_state()
    if current == source:
        logger.info("Audio already %s", source)
        if publish:
            publish_state(client, AUDIO_STATE_TOPIC, current)
        return

    target = AUDIO_DAC if source == "dac" else AUDIO_MIXER
    GPIO.output(AUDIO_PIN, target)
    new_state = current_audio_state()
    logger.info("Audio changed: %s -> %s", current, new_state)
    if publish:
        publish_state(client, AUDIO_STATE_TOPIC, new_state)


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

    target = TRIGGER_ON if state == "on" else TRIGGER_OFF
    GPIO.output(TRIGGER_PIN, target)
    new_state = current_trigger_state()
    logger.info("Trigger changed: %s -> %s", current, new_state)
    if publish:
        publish_state(client, TRIGGER_STATE_TOPIC, new_state)


def apply_safe_defaults(client=None, publish=False):
    GPIO.output(AUDIO_PIN, AUDIO_MIXER)
    GPIO.output(TRIGGER_PIN, TRIGGER_OFF)
    logger.info("Applied safe defaults: audio=mixer, trigger=off")

    if client is not None and publish:
        publish_state(client, AUDIO_STATE_TOPIC, current_audio_state())
        publish_state(client, TRIGGER_STATE_TOPIC, current_trigger_state())


def on_connect(client, userdata, flags, reason_code, properties):
    logger.info("Connected to MQTT: reason_code=%s", reason_code)
    client.subscribe(AUDIO_COMMAND_TOPIC)
    client.subscribe(TRIGGER_COMMAND_TOPIC)
    client.publish(AVAILABILITY_TOPIC, "online", retain=True)
    publish_state(client, AUDIO_STATE_TOPIC, current_audio_state())
    publish_state(client, TRIGGER_STATE_TOPIC, current_trigger_state())


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    if reason_code.value == 0:
        logger.info("Disconnected from MQTT")
    else:
        logger.warning("MQTT disconnected unexpectedly: reason_code=%s", reason_code)


def on_message(client, userdata, msg):
    payload = normalize_payload(msg.payload)
    logger.info("Incoming %s -> %s", msg.topic, payload)

    if msg.topic == AUDIO_COMMAND_TOPIC:
        set_audio(client, payload)
    elif msg.topic == TRIGGER_COMMAND_TOPIC:
        set_trigger(client, payload)


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(AUDIO_PIN, GPIO.OUT, initial=AUDIO_MIXER)
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
        apply_safe_defaults(client, publish=False)
        GPIO.cleanup()


if __name__ == "__main__":
    main()
