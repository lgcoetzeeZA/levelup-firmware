import ujson
import os

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "wifi_networks": [],       # list of {"ssid": ..., "pwd": ...}
    "wifi_default_ssid": "",   # which saved network to try first
    "tank_liters": 0,
    "tank_height": 0,
    "tank_diameter": 0,
    "mqtt_client_id": ""
}


def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            config = ujson.load(f)
    except (OSError, ValueError):
        return dict(DEFAULT_CONFIG)

    # Migrate legacy single-network format (wifi_ssid/wifi_pwd) to the
    # new wifi_networks list, so existing devices upgrade automatically.
    if "wifi_networks" not in config:
        legacy_ssid = config.get("wifi_ssid", "")
        legacy_pwd = config.get("wifi_pwd", "")
        if legacy_ssid:
            config["wifi_networks"] = [{"ssid": legacy_ssid, "pwd": legacy_pwd}]
            config["wifi_default_ssid"] = legacy_ssid
        else:
            config["wifi_networks"] = []
            config["wifi_default_ssid"] = ""

    # Backfill any keys missing from an older config version
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value

    # Drop stale legacy fields now that they've been migrated - keeping
    # them around only invites confusion since nothing reads them anymore.
    config.pop("wifi_ssid", None)
    config.pop("wifi_pwd", None)

    return config


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        ujson.dump(config, f)


def is_configured(config):
    return (
        bool(config.get("wifi_networks"))
        and config.get("tank_height", 0) > 0
        and config.get("tank_diameter", 0) > 0
    )


def clear_config():
    try:
        os.remove(CONFIG_FILE)
    except OSError:
        pass
