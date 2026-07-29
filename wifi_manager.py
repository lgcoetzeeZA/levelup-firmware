import network
import time


def connect(ssid, password, timeout=20):
    """Try to connect to WiFi using the given credentials.
    Returns the WLAN object on success, or None on failure/timeout."""
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)

    if wifi.isconnected():
        return wifi

    print("Connecting to WiFi: {}".format(ssid))

    try:
        wifi.connect(ssid, password)
    except OSError as e:
        print("WiFi connect() raised an error:", e)
        # This often means the radio driver is in a bad state from a
        # previous connect/disconnect cycle - toggling it off and back on
        # clears that before we give up on this network.
        try:
            wifi.active(False)
            time.sleep(0.5)
            wifi.active(True)
        except OSError:
            pass
        return None

    start = time.time()
    while not wifi.isconnected():
        if time.time() - start > timeout:
            print("WiFi connection timed out")
            wifi.active(False)
            return None
        time.sleep(0.5)

    print("Connected. IP:", wifi.ifconfig()[0])
    return wifi


def connect_multi(networks, default_ssid, timeout_per_network=15, on_attempt=None):
    """Try connecting to each saved network in priority order - the default
    first, then the rest in the order they were saved. Returns the WLAN
    object on the first success, or None if every network failed.

    on_attempt(ssid): optional callback fired right before each attempt,
    useful for showing "Connecting to: <ssid>" on a display."""
    if not networks:
        return None

    ordered = []
    default_net = None
    for net in networks:
        if net["ssid"] == default_ssid:
            default_net = net
        else:
            ordered.append(net)
    if default_net:
        ordered.insert(0, default_net)
    else:
        ordered = networks  # no valid default set - just try saved order

    for net in ordered:
        if on_attempt:
            on_attempt(net["ssid"])
        wifi = connect(net["ssid"], net["pwd"], timeout=timeout_per_network)
        if wifi is not None:
            return wifi
        print("Failed to connect to", net["ssid"])

    return None


def disconnect_ap():
    ap = network.WLAN(network.AP_IF)
    ap.active(False)
