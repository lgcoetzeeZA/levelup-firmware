import time
import ujson
import ubinascii
import machine
from machine import Pin, WDT

from config_manager import load_config, save_config, is_configured
import wifi_manager
import setup_portal
import status_led
import display
import reservoir_sensor
import mqtt_handler
import buttons
import relay_state
import rgb_led
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


def make_on_message(state, wdt, ota_progress, config, publish_config, publish_data_now, publish_status_retained):
    """Returns an MQTT message callback closed over shared loop state,
    so incoming commands (e.g. relay toggle) can update the relay pin."""
    def on_message(topic, msg):
        print("MQTT message on {}: {}".format(topic, msg))
        if msg == b"relayOn":
            set_relay(1)
            print("Relay set ON via MQTT")
            ota_progress("Relay set ON via MQTT")
        elif msg == b"relayOff":
            set_relay(0)
            print("Relay set OFF via MQTT")
            ota_progress("Relay set OFF via MQTT")
        elif msg in (b"RelayToggle", b"startRelay"):
            set_relay(not relay.value())
            print("Relay toggled via MQTT ->", relay.value())
            ota_progress("Relay toggled via MQTT -> {}".format("ON" if relay.value() else "OFF"))
        elif msg in (b"rebootDevice", b"restartDevice", b"restart", b"reboot"):
            print("Reboot requested via MQTT")
            ota_progress("Rebooting device now...")
            time.sleep(1)
            machine.reset()
        elif msg in (b"checkForUpdate", b"update", b"ota"):
            print("OTA check requested via MQTT")
            ota_updater.check_for_update(display=display, wdt=wdt, on_progress=ota_progress)
        elif msg in (b"enterSetup", b"addNetwork", b"setup"):
            print("Setup portal requested via MQTT")
            ota_progress(
                "Entering setup mode. Connect to WiFi '{}' (password: {}), then "
                "browse to http://192.168.4.1 to add/manage WiFi networks. "
                "Device will be offline until you finish or it times out in 5 "
                "minutes.".format(setup_portal.AP_SSID, setup_portal.AP_PASSWORD)
            )
            publish_status_retained("setup_mode")
            setup_portal.run_setup_portal(mode="add_network", wdt=wdt)
            # unreachable - run_setup_portal always ends in machine.reset()
        elif msg == b"status":
            print("Status requested via MQTT")
            publish_config()
            publish_data_now()
        elif msg.startswith(b"{"):
            try:
                cmd = ujson.loads(msg)
                if cmd.get("cmd") == "setTank":
                    if "liters" in cmd:
                        config["tank_liters"] = float(cmd["liters"])
                    if "height" in cmd:
                        config["tank_height"] = float(cmd["height"])
                    if "diameter" in cmd:
                        config["tank_diameter"] = float(cmd["diameter"])
                    if "sensor_offset" in cmd:
                        config["sensor_offset_cm"] = float(cmd["sensor_offset"])
                    save_config(config)
                    print("Tank settings updated via MQTT:", config)
                    ota_progress("Tank settings updated: height={} diameter={} offset={} liters={}".format(
                        config["tank_height"], config["tank_diameter"],
                        config["sensor_offset_cm"], config["tank_liters"]
                    ))
                    publish_config()
                else:
                    print("Unknown JSON command:", cmd)
                    ota_progress("Unknown command: {}".format(cmd.get("cmd", "?")))
            except (ValueError, KeyError, TypeError) as e:
                print("Failed to parse JSON command:", e)
                ota_progress("Command failed - check JSON format")
        else:
            print("Unrecognized command:", msg)
            ota_progress("Unrecognized command: {}".format(msg))
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


def build_status_payload(wifi, reading, relay_state, config):
    now = time.localtime()
    timestamp = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        now[0], now[1], now[2], now[3], now[4], now[5]
    )

    level = reading["level"] or {}

    return {
        "sensor_type": reservoir_sensor.get_sensor_type(),
        "sensor_status": reading["status"],
        "distance_cm": reading["distance_cm"],
        "consecutive_failures": reading["consecutive_failures"],
        "seconds_since_good": reading.get("seconds_since_good"),
        "level_pct": level.get("percent"),
        "water_cm": level.get("water_height_cm"),
        "volume_l": level.get("available_liters"),
        "tank_volume_l": level.get("capacity_liters"),
        "tank_overflow_cm": config.get("tank_height"),
        "tank_diameter_cm": config.get("tank_diameter"),
        "sensor_from_overflow_cm": config.get("sensor_offset_cm"),
        "relay_status": int(relay_state),
        "dip1": dip1.value(),
        "dip2": dip2.value(),
        "oled_connected": display.available(),
        "version": ota_updater.get_current_version(),
        "ssid": str(wifi.config("essid")) if wifi else None,
        "rssi": wifi.status("rssi") if wifi else None,
        "wifi_signal_pct": rssi_to_percent(wifi.status("rssi")) if wifi else None,
        "ip": wifi.ifconfig()[0] if wifi else None,
        "timestamp": timestamp,
    }


def build_config_payload(config, client_id):
    return {
        "firmware": "LevelUp",
        "version": ota_updater.get_current_version(),
        "prefix": client_id,
        "tank_diameter_cm": config.get("tank_diameter"),
        "tank_overflow_cm": config.get("tank_height"),
        "sensor_from_overflow_cm": config.get("sensor_offset_cm"),
        "tank_roof_cm": (config.get("tank_height") or 0) + (config.get("sensor_offset_cm") or 0),
        "tank_liters": config.get("tank_liters"),
    }


def update_display(reading, mqtt_connected, wifi_signal_percent, relay_on):
    level = reading["level"]
    percent = level["percent"] if level else None
    available = level["available_liters"] if level else None
    capacity = level["capacity_liters"] if level else None

    display.show_dashboard(
        percent, available, capacity,
        wifi_signal_percent, mqtt_connected,
        reading["status"], relay_on
    )


def run_app(config, wifi):
    client_id = get_client_id(config)
    print("MQTT client ID:", client_id)

    topic_data = "{}/{}/data".format(client_id, MQTT_TOPIC_PREFIX)
    topic_cmd = "{}/{}/cmd".format(client_id, MQTT_TOPIC_PREFIX)
    topic_relay = "{}/{}/relay".format(client_id, MQTT_TOPIC_PREFIX)
    topic_progress = "{}/{}/progress".format(client_id, MQTT_TOPIC_PREFIX)
    topic_status = "{}/{}/status".format(client_id, MQTT_TOPIC_PREFIX)
    topic_config = "{}/{}/config".format(client_id, MQTT_TOPIC_PREFIX)

    wdt = WDT(timeout=WDT_TIMEOUT_MS)

    last_publish = time.time()
    last_relay_published = None
    last_ota_check = time.time()
    was_mqtt_connected = False

    def ota_progress(message):
        mqtt.publish_raw(topic_progress, message)

    def publish_status_retained(status_msg):
        mqtt.publish_raw(topic_status, status_msg, retain=True)

    def publish_config():
        mqtt.publish_json(topic_config, build_config_payload(config, client_id))

    def publish_data_now():
        nonlocal last_publish
        reading = reservoir_sensor.read(config)
        wifi_signal_pct = rssi_to_percent(wifi.status("rssi")) if wifi else None
        update_display(reading, mqtt.connected, wifi_signal_pct, bool(relay.value()))
        if rgb:
            rgb.set_percent(reading["level"]["percent"] if reading["level"] else None)
        payload = build_status_payload(wifi, reading, relay.value(), config)
        published = mqtt.publish_json(topic_data, payload)
        if not wifi.isconnected():
            status_led.set_status(status_led.STATUS_WIFI_FAILED)
        elif not mqtt.connected:
            status_led.set_status(status_led.STATUS_MQTT_FAILED)
        else:
            status_led.set_status(status_led.STATUS_CONNECTED)
        print("Published" if published else "Publish skipped (MQTT not connected)", payload)
        last_publish = time.time()

    state = {}
    mqtt = mqtt_handler.MQTTHandler(
        client_id=client_id,
        server=MQTT_BROKER,
        sub_topic=topic_cmd,
        on_message=make_on_message(state, wdt, ota_progress, config, publish_config, publish_data_now, publish_status_retained),
        keepalive=60,
        lw_topic=topic_status,
        lw_msg="offline",
    )

    while True:
        wdt.feed()

        if not wifi.isconnected():
            print("WiFi dropped - restarting to re-provision.")
            machine.reset()

        mqtt.ensure_connected()
        if mqtt.connected and not was_mqtt_connected:
            publish_config()
        was_mqtt_connected = mqtt.connected
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
            publish_status_retained("setup_mode")
            time.sleep(1)
            setup_portal.run_setup_portal(mode="add_network", wdt=wdt)
            return  # unreachable - portal loops until the device resets

        if dip1.value() == 1 and dip2.value() == 0:
            if left_button.check_hold(OTA_BUTTON_HOLD_MS):
                print("Checking for firmware update via button (dip1 armed)")
                display.show("Checking for", "Update...", "", "")
                ota_updater.check_for_update(display=display, wdt=wdt, on_progress=ota_progress)
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
            publish_data_now()

        if time.time() - last_ota_check >= OTA_CHECK_INTERVAL_SEC:
            print("Running scheduled OTA check...")
            ota_updater.check_for_update(display=display, wdt=wdt, on_progress=ota_progress)
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
