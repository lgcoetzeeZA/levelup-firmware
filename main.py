import time
import ujson
import ubinascii
import machine
from machine import Pin, WDT

from config_manager import load_config, is_configured
import wifi_manager
import setup_portal
import status_led
import display
import reservoir_sensor
import mqtt_handler
import buttons
import relay_state
import rgb_led
import indicator_led
import ota_updater

# ---------------------------------------------------------------------------
# CONFIG / CONSTANTS
# ---------------------------------------------------------------------------
MQTT_BROKER = "broker.hivemq.com"
MQTT_TOPIC_PREFIX = "LevelUp"
PUBLISH_INTERVAL_SEC = 5
OTA_CHECK_INTERVAL_SEC = 24 * 60 * 60  # once a day
WDT_TIMEOUT_MS = 30000
RELAY_PIN = 17
RELAY_BUTTON_PIN = 16
RELAY_HOLD_MS = 3000
RIGHT_BUTTON_PIN = 4
ADD_NETWORK_HOLD_MS = 5000
LEFT_BUTTON_PIN = 12
EDIT_TANK_HOLD_MS = 5000
OTA_BUTTON_HOLD_MS = 3000
DIP1_PIN = 14
DIP2_PIN = 13
GREEN_LED_PIN = 5
RGB_RED_PIN = 32
RGB_GREEN_PIN = 25
RGB_BLUE_PIN = 33

# Set to False when the RGB LED feather board isn't plugged in - there's no
# way to auto-detect a bare LED on PWM pins the way we can probe the OLED's
# I2C bus, so this is a manual switch.
RGB_LED_ENABLED = True

relay = Pin(RELAY_PIN, Pin.OUT)
relay.value(relay_state.load_relay_state())
print("Relay resumed to saved state:", relay.value())

green_led = indicator_led.IndicatorLED(GREEN_LED_PIN)

rgb = rgb_led.RGBLed(RGB_RED_PIN, RGB_GREEN_PIN, RGB_BLUE_PIN) if RGB_LED_ENABLED else None

dip1 = Pin(DIP1_PIN, Pin.IN, Pin.PULL_DOWN)
dip2 = Pin(DIP2_PIN, Pin.IN, Pin.PULL_DOWN)

relay_button = buttons.Button(RELAY_BUTTON_PIN, Pin.PULL_DOWN)
right_button = buttons.Button(RIGHT_BUTTON_PIN, Pin.PULL_DOWN)
left_button = buttons.Button(LEFT_BUTTON_PIN, Pin.PULL_DOWN)


def set_relay(value):
    relay.value(value)
    relay_state.save_relay_state(value)


def get_client_id(config):
    """Use the user's chosen MQTT client ID if they set one during setup,
    otherwise fall back to an ID generated from the chip's hardware ID -
    so it's always unique and never blank."""
    client_id = config.get("mqtt_client_id", "").strip()
    if not client_id:
        client_id = ubinascii.hexlify(machine.unique_id()).decode()
    return client_id


def make_on_message(state, wdt):
    """Returns an MQTT message callback closed over shared loop state,
    so incoming commands (e.g. relay toggle) can update the relay pin."""
    def on_message(topic, msg):
        print("MQTT message on {}: {}".format(topic, msg))
        if msg == b"relayOn":
            set_relay(1)
            print("Relay set ON via MQTT")
        elif msg == b"relayOff":
            set_relay(0)
            print("Relay set OFF via MQTT")
        elif msg in (b"RelayToggle", b"startRelay"):
            set_relay(not relay.value())
            print("Relay toggled via MQTT ->", relay.value())
        elif msg == b"checkForUpdate":
            print("OTA check requested via MQTT")
            ota_updater.check_for_update(display=display, wdt=wdt)
    return on_message


def rssi_to_percent(rssi):
    """Converts WiFi RSSI (dBm, typically -30 to -90) to a 0-100 signal
    quality percentage - useful for app gauge widgets that don't handle
    negative numbers well. -50 dBm or better = 100%, -100 dBm or worse = 0%."""
    if rssi is None:
        return None
    if rssi <= -100:
        return 0
    if rssi >= -50:
        return 100
    return int(2 * (rssi + 100))


def build_status_payload(wifi, reading, relay_state):
    now = time.localtime()
    timestamp = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        now[0], now[1], now[2], now[3], now[4], now[5]
    )

    level = reading["level"] or {}

    return {
        "sensorStatus": reading["status"],
        "distanceCm": reading["distance_cm"],
        "consecutiveFailures": reading["consecutive_failures"],
        "tankPercent": level.get("percent"),
        "tankAvailableLiters": level.get("available_liters"),
        "tankCapacityLiters": level.get("capacity_liters"),
        "relayStatus": int(relay_state),
        "dip1": dip1.value(),
        "dip2": dip2.value(),
        "oledConnected": display.available(),
        "firmwareVersion": ota_updater.get_current_version(),
        "wifiSSID": str(wifi.config("essid")) if wifi else None,
        "wifiRSSI": wifi.status("rssi") if wifi else None,
        "wifiSignalPercent": rssi_to_percent(wifi.status("rssi")) if wifi else None,
        "ipAddress": wifi.ifconfig()[0] if wifi else None,
        "timestamp": timestamp,
    }


def update_display(reading, mqtt_connected):
    level = reading["level"]
    lines = []

    if reading["status"] == "ok":
        lines.append("Tank: {}%".format(level["percent"]))
        lines.append("{} / {} L".format(level["available_liters"], level["capacity_liters"]))
    elif level:
        lines.append("Tank: {}%".format(level["percent"]))
        lines.append("(last reading)")
    else:
        lines.append("No tank reading yet")

    if reading["status"] == "stale":
        lines.append("Sensor Error")
    elif reading["status"] == "error":
        lines.append("SENSOR ERROR")

    if not mqtt_connected:
        lines.append("MQTT Offline")

    display.show(*lines[:5])


def run_app(config, wifi):
    client_id = get_client_id(config)
    print("MQTT client ID:", client_id)

    topic_pub = "{}/{}/pub".format(client_id, MQTT_TOPIC_PREFIX)
    topic_sub = "{}/{}/sub".format(client_id, MQTT_TOPIC_PREFIX)
    topic_relay = "{}/{}/relay".format(client_id, MQTT_TOPIC_PREFIX)

    wdt = WDT(timeout=WDT_TIMEOUT_MS)

    state = {}
    mqtt = mqtt_handler.MQTTHandler(
        client_id=client_id,
        server=MQTT_BROKER,
        sub_topic=topic_sub,
        on_message=make_on_message(state, wdt),
        keepalive=60,
    )

    last_publish = time.time()
    last_relay_published = None
    last_ota_check = time.time()

    while True:
        wdt.feed()

        if not wifi.isconnected():
            print("WiFi dropped - restarting to re-provision.")
            machine.reset()

        mqtt.ensure_connected()
        mqtt.check_messages()
        mqtt.keepalive_ping()

        if relay_button.check_hold(RELAY_HOLD_MS):
            set_relay(not relay.value())
            print("Relay toggled via button ->", relay.value())
            display.show("Relay Toggled", "", "Relay: {}".format("ON" if relay.value() else "OFF"))
            time.sleep(1)

        if right_button.check_hold(ADD_NETWORK_HOLD_MS):
            print("Entering Add Network setup mode via button hold")
            display.show("Add Network", "", "Entering setup", "mode...")
            time.sleep(1)
            setup_portal.run_setup_portal(mode="add_network", wdt=wdt)
            return  # unreachable - portal loops until the device resets

        if dip1.value() == 1:
            if left_button.check_hold(OTA_BUTTON_HOLD_MS):
                print("Checking for firmware update via button (dip1 armed)")
                display.show("Checking for", "Update...", "", "")
                ota_updater.check_for_update(display=display, wdt=wdt)
                display.show("Check Complete", "", "", "")
                time.sleep(2)
        else:
            if left_button.check_hold(EDIT_TANK_HOLD_MS):
                print("Entering tank settings edit mode via button hold")
                display.show("Edit Tank", "", "Starting server...")
                time.sleep(1)
                setup_portal.run_edit_tank_server(wdt=wdt)
                return  # unreachable - server loops until the device resets

        if relay.value() != last_relay_published:
            payload = b"relayOn" if relay.value() else b"relayOff"
            if mqtt.publish_raw(topic_relay, payload):
                last_relay_published = relay.value()
                print("Published relay state:", payload)

        if time.time() - last_publish >= PUBLISH_INTERVAL_SEC:
            reading = reservoir_sensor.read(config)
            update_display(reading, mqtt.connected)
            if rgb:
                rgb.set_percent(reading["level"]["percent"] if reading["level"] else None)

            if reading["status"] != "ok":
                green_led.set_mode(indicator_led.OFF)
            elif reading["level"]["percent"] > 20:
                green_led.set_mode(indicator_led.ON)
            else:
                green_led.set_mode(indicator_led.BLINK)

            payload = build_status_payload(wifi, reading, relay.value())
            published = mqtt.publish_json(topic_pub, payload)

            if not wifi.isconnected():
                status_led.set_status(status_led.STATUS_WIFI_FAILED)
            elif not mqtt.connected:
                status_led.set_status(status_led.STATUS_MQTT_FAILED)
            else:
                status_led.set_status(status_led.STATUS_CONNECTED)

            print("Published" if published else "Publish skipped (MQTT not connected)", payload)

            last_publish = time.time()

        if time.time() - last_ota_check >= OTA_CHECK_INTERVAL_SEC:
            print("Running scheduled OTA check...")
            ota_updater.check_for_update(display=display, wdt=wdt)
            last_ota_check = time.time()

        time.sleep(0.2)


def main():
    config = load_config()

    if not is_configured(config):
        print("Device not configured yet. Starting setup portal...")
        status_led.set_status(status_led.STATUS_NOT_CONFIGURED)
        display.show("LevelUp", "", "Setup required", "", "Starting...")
        setup_portal.run_setup_portal()
        return  # unreachable - portal loops until the device resets

    status_led.set_status(status_led.STATUS_CONNECTING)
    display.show("Connecting to:", "saved networks", "", "Please wait...")

    def show_attempt(ssid):
        display.show("Connecting to:", ssid, "", "Please wait...")

    wifi = wifi_manager.connect_multi(
        config["wifi_networks"],
        config["wifi_default_ssid"],
        timeout_per_network=15,
        on_attempt=show_attempt,
    )

    if wifi is None:
        print("Could not connect with saved WiFi credentials. Starting setup portal...")
        status_led.set_status(status_led.STATUS_WIFI_FAILED)
        display.show("WiFi Connect", "FAILED", "", "Restarting into", "setup mode...")
        time.sleep(3)
        setup_portal.run_setup_portal()
        return

    status_led.set_status(status_led.STATUS_CONNECTED)
    ip = wifi.ifconfig()[0]
    print("WiFi connected. IP:", ip)
    display.show("WiFi Connected", "IP: " + ip, "", "Starting app...")
    time.sleep(2)

    run_app(config, wifi)


if __name__ == "__main__":
    main()
