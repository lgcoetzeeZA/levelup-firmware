import network
import socket
import time
import machine
from config_manager import load_config, save_config
import status_led
import display

AP_SSID = "LevelUp-Setup"
AP_PASSWORD = "levelup123"  # must be 8+ characters for WPA2


def _url_decode(s):
    s = s.replace("+", " ")
    result = ""
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try:
                result += chr(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        result += s[i]
        i += 1
    return result


def _html_escape(s):
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&#39;"))


def _parse_form(body):
    fields = {}
    for pair in body.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            fields[_url_decode(key)] = _url_decode(value)
    return fields


def _scan_networks():
    sta = network.WLAN(network.STA_IF)
    was_active = sta.active()
    sta.active(True)

    networks = []
    try:
        results = sta.scan()
        seen = set()
        for ssid, bssid, channel, rssi, authmode, hidden in results:
            name = ssid.decode("utf-8", "ignore") if isinstance(ssid, bytes) else ssid
            if not name or name in seen:
                continue
            seen.add(name)
            networks.append((name, rssi))
        networks.sort(key=lambda x: x[1], reverse=True)
    except OSError as e:
        print("WiFi scan failed:", e)

    if not was_active:
        sta.active(False)

    return networks


def _ssid_dropdown_html(scanned_networks, include_none_option=False):
    none_option = '<option value="__none__" selected>-- Leave unchanged, no new network --</option>\n' if include_none_option else ""

    if scanned_networks:
        options = ""
        for name, rssi in scanned_networks:
            safe_name = _html_escape(name)
            options += '<option value="{0}">{0} ({1} dBm)</option>\n'.format(safe_name, rssi)
        options += '<option value="__other__">Other (enter manually)</option>'
        manual_display = "none"
    else:
        options = '<option value="__other__"{0}>Other (enter manually)</option>'.format(
            "" if include_none_option else " selected"
        )
        manual_display = "none" if include_none_option else "block"

    return none_option + options, manual_display


def _page_shell(title, body):
    return """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{font-family:sans-serif;background:#101820;color:#eee;padding:20px;max-width:420px;margin:0 auto}}
h1{{color:#4fc3f7;font-size:22px}}
h2{{color:#4fc3f7;font-size:16px;margin-top:24px;border-top:1px solid #333;padding-top:16px}}
label{{display:block;margin-top:14px;font-size:14px}}
input,select{{width:100%;padding:10px;margin-top:4px;box-sizing:border-box;border-radius:6px;border:none;font-size:15px}}
button{{margin-top:22px;width:100%;padding:12px;background:#4fc3f7;border:none;border-radius:6px;font-size:16px;font-weight:bold}}
.network-row{{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #222}}
.network-row input[type=radio]{{width:auto;margin:0}}
.network-row span{{flex:1;font-size:14px}}
.badge{{font-size:11px;background:#4fc3f7;color:#101820;padding:2px 6px;border-radius:4px}}
</style>
</head>
<body>
<h1>{title}</h1>
{body}
</body>
</html>""".format(title=title, body=body)


def _render_full_setup_page(scanned_networks, error=None):
    error_html = "<p style='color:#ff6b6b'>{}</p>".format(error) if error else ""
    options, manual_display = _ssid_dropdown_html(scanned_networks)

    body = """
{error}
<form method="POST" action="/">
<label>WiFi Network</label>
<select name="ssid_select" id="ssid_select" onchange="toggleManual()">
{options}
</select>
<div id="manual_wrap" style="display:{manual_display}">
<label>Network Name (SSID)</label>
<input type="text" name="ssid_manual" id="ssid_manual">
</div>
<label>WiFi Password</label>
<input type="password" name="pwd">
<label>Tank Capacity (Liters)</label>
<input type="number" step="any" name="liters" required>
<label>Tank Height (cm)</label>
<input type="number" step="any" name="height" required>
<label>Tank Diameter (cm)</label>
<input type="number" step="any" name="diameter" required>
<label>Sensor Height Above Full Water Line (cm)</label>
<input type="number" step="any" name="sensor_offset" placeholder="Leave blank if sensor sits flush at the top">
<label>Number of Tanks Connected (identical, sharing one water level)</label>
<input type="number" step="1" min="1" name="tank_count" value="1">
<label>MQTT Client ID (optional)</label>
<input type="text" name="mqtt_client_id" placeholder="Leave blank for auto-generated ID">
<button type="submit">Save &amp; Connect</button>
</form>
<script>
function toggleManual(){{
  var sel = document.getElementById('ssid_select');
  var wrap = document.getElementById('manual_wrap');
  wrap.style.display = (sel.value === '__other__') ? 'block' : 'none';
}}
</script>
""".format(error=error_html, options=options, manual_display=manual_display)

    return _page_shell("LevelUp Device Setup", body)


def _render_add_network_page(scanned_networks, existing_networks, default_ssid, config, error=None):
    error_html = "<p style='color:#ff6b6b'>{}</p>".format(error) if error else ""
    options, manual_display = _ssid_dropdown_html(scanned_networks, include_none_option=True)

    saved_rows = ""
    if existing_networks:
        for net in existing_networks:
            safe_ssid = _html_escape(net["ssid"])
            checked = "checked" if net["ssid"] == default_ssid else ""
            saved_rows += """<div class="network-row">
<input type="radio" name="default_choice" value="{ssid}" {checked}>
<span>{ssid}</span>{badge}
</div>""".format(
                ssid=safe_ssid,
                checked=checked,
                badge=' <span class="badge">DEFAULT</span>' if checked else ""
            )
    else:
        saved_rows = "<p>No networks saved yet.</p>"

    body = """
{error}
<h2>Saved Networks</h2>
<form method="POST" action="/">
{saved_rows}
<h2>Add a New Network (optional)</h2>
<label>WiFi Network</label>
<select name="ssid_select" id="ssid_select" onchange="toggleManual()">
{options}
</select>
<div id="manual_wrap" style="display:{manual_display}">
<label>Network Name (SSID)</label>
<input type="text" name="ssid_manual" id="ssid_manual">
</div>
<label>WiFi Password</label>
<input type="password" name="pwd">
<div class="network-row">
<input type="radio" name="default_choice" value="__new__">
<span>Make this new network the default</span>
</div>
<h2>Tank Settings</h2>
<label>Tank Capacity (Liters)</label>
<input type="number" step="any" name="liters" value="{liters}" required>
<label>Tank Height (cm)</label>
<input type="number" step="any" name="height" value="{height}" required>
<label>Tank Diameter (cm)</label>
<input type="number" step="any" name="diameter" value="{diameter}" required>
<label>Sensor Height Above Full Water Line (cm)</label>
<input type="number" step="any" name="sensor_offset" value="{sensor_offset}">
<label>Number of Tanks Connected (identical, sharing one water level)</label>
<input type="number" step="1" min="1" name="tank_count" value="{tank_count}">
<button type="submit">Save</button>
</form>
<script>
function toggleManual(){{
  var sel = document.getElementById('ssid_select');
  var wrap = document.getElementById('manual_wrap');
  wrap.style.display = (sel.value === '__other__') ? 'block' : 'none';
}}
</script>
""".format(
        error=error_html, saved_rows=saved_rows, options=options,
        manual_display=manual_display,
        liters=config.get("tank_liters", 0),
        height=config.get("tank_height", 0),
        diameter=config.get("tank_diameter", 0),
        sensor_offset=config.get("sensor_offset_cm", 0),
        tank_count=config.get("tank_count", 1),
    )

    return _page_shell("Manage WiFi Networks", body)


def _success_page(message):
    body = """<div style="text-align:center">
<p>{}</p>
<p>The device will now restart.</p>
</div>""".format(_html_escape(message))
    return _page_shell("Saved", body)


def _resolve_new_ssid(fields):
    ssid_select = fields.get("ssid_select", "")
    if ssid_select and ssid_select not in ("__other__", "__none__"):
        return ssid_select
    return fields.get("ssid_manual", "").strip()


def _handle_full_setup_post(fields, scanned_networks):
    try:
        ssid = _resolve_new_ssid(fields)
        pwd = fields.get("pwd", "")
        liters = float(fields.get("liters", 0))
        height = float(fields.get("height", 0))
        diameter = float(fields.get("diameter", 0))
        offset_raw = fields.get("sensor_offset", "").strip()
        sensor_offset = float(offset_raw) if offset_raw else 0.0
        count_raw = fields.get("tank_count", "").strip()
        tank_count = int(float(count_raw)) if count_raw else 1
        if tank_count < 1:
            tank_count = 1

        if not ssid or height <= 0 or diameter <= 0:
            raise ValueError("missing required field")

        config = load_config()

        # Merge into the existing network list rather than replacing it -
        # otherwise running full setup again (e.g. after a WiFi failure)
        # would silently wipe out any other networks added via Add Network.
        networks = config.get("wifi_networks", [])
        found = False
        for net in networks:
            if net["ssid"] == ssid:
                net["pwd"] = pwd
                found = True
                break
        if not found:
            networks.append({"ssid": ssid, "pwd": pwd})
        config["wifi_networks"] = networks
        config["wifi_default_ssid"] = ssid

        config["tank_liters"] = liters
        config["tank_height"] = height
        config["tank_diameter"] = diameter
        config["sensor_offset_cm"] = sensor_offset
        config["tank_count"] = tank_count
        config["mqtt_client_id"] = fields.get("mqtt_client_id", "").strip()
        save_config(config)

        status_led.set_status(status_led.STATUS_SAVED)
        display.show("Settings Saved", "", "Restarting...")
        return _success_page("Settings saved. Connecting to {}.".format(ssid)), True
    except (ValueError, KeyError):
        return _render_full_setup_page(scanned_networks, error="Please fill in all fields with valid numbers."), False


def _handle_add_network_post(fields, scanned_networks):
    try:
        config = load_config()
        networks = config.get("wifi_networks", [])

        new_ssid = _resolve_new_ssid(fields)
        new_pwd = fields.get("pwd", "")

        if new_ssid:
            found = False
            for net in networks:
                if net["ssid"] == new_ssid:
                    if new_pwd:  # never blank out an existing saved password
                        net["pwd"] = new_pwd
                    found = True
                    break
            if not found:
                networks.append({"ssid": new_ssid, "pwd": new_pwd})
            config["wifi_networks"] = networks

        default_choice = fields.get("default_choice", "")
        if default_choice == "__new__":
            if not new_ssid:
                raise ValueError("selected new network as default but none was entered")
            config["wifi_default_ssid"] = new_ssid
        elif default_choice:
            valid_ssids = [n["ssid"] for n in config.get("wifi_networks", [])]
            if default_choice in valid_ssids:
                config["wifi_default_ssid"] = default_choice

        if not config.get("wifi_networks"):
            raise ValueError("no networks saved")

        liters = float(fields.get("liters", 0))
        height = float(fields.get("height", 0))
        diameter = float(fields.get("diameter", 0))
        offset_raw = fields.get("sensor_offset", "").strip()
        sensor_offset = float(offset_raw) if offset_raw else 0.0
        count_raw = fields.get("tank_count", "").strip()
        tank_count = int(float(count_raw)) if count_raw else 1
        if tank_count < 1:
            tank_count = 1

        if height <= 0 or diameter <= 0:
            raise ValueError("missing required tank field")

        config["tank_liters"] = liters
        config["tank_height"] = height
        config["tank_diameter"] = diameter
        config["sensor_offset_cm"] = sensor_offset
        config["tank_count"] = tank_count

        save_config(config)

        status_led.set_status(status_led.STATUS_SAVED)
        display.show("Settings Saved", "", "Restarting...")
        return _success_page("Network and tank settings saved."), True
    except (ValueError, KeyError):
        config = load_config()
        return _render_add_network_page(
            scanned_networks,
            config.get("wifi_networks", []),
            config.get("wifi_default_ssid", ""),
            config,
            error="Please check the form and try again."
        ), False


def _read_full_request(client, max_bytes=8192):
    """Reads a complete HTTP request from the socket, looping until the
    full body has arrived (per Content-Length) rather than assuming a
    single recv() call captures everything - a request can legitimately
    arrive across multiple TCP packets, especially once the body is more
    than a few dozen bytes."""
    try:
        client.settimeout(3)
    except OSError:
        pass

    buffer = b""
    header_end = -1

    while header_end == -1:
        try:
            chunk = client.recv(1024)
        except OSError:
            break
        if not chunk:
            break
        buffer += chunk
        header_end = buffer.find(b"\r\n\r\n")
        if len(buffer) > max_bytes:
            break

    if header_end == -1:
        return buffer.decode("utf-8", "ignore")

    headers_part = buffer[:header_end].decode("utf-8", "ignore")
    body_so_far = buffer[header_end + 4:]

    content_length = 0
    for line in headers_part.split("\r\n"):
        if line.lower().startswith("content-length:"):
            try:
                content_length = int(line.split(":", 1)[1].strip())
            except ValueError:
                content_length = 0
            break

    while len(body_so_far) < content_length and len(body_so_far) < max_bytes:
        try:
            chunk = client.recv(1024)
        except OSError:
            break
        if not chunk:
            break
        body_so_far += chunk

    return headers_part + "\r\n\r\n" + body_so_far.decode("utf-8", "ignore")


def _handle_request(client, mode, scanned_networks):
    try:
        request = _read_full_request(client)

        header_end = request.find("\r\n\r\n")
        body = request[header_end + 4:] if header_end != -1 else ""

        if request.startswith("POST"):
            fields = _parse_form(body)
            print("POST fields received:", fields)
            if mode == "add_network":
                page, success = _handle_add_network_post(fields, scanned_networks)
            else:
                page, success = _handle_full_setup_post(fields, scanned_networks)

            client.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n")
            client.sendall(page)
            client.close()

            if success:
                time.sleep(2)
                machine.reset()
        else:
            if mode == "add_network":
                config = load_config()
                page = _render_add_network_page(
                    scanned_networks,
                    config.get("wifi_networks", []),
                    config.get("wifi_default_ssid", ""),
                    config
                )
            else:
                page = _render_full_setup_page(scanned_networks)

            client.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n")
            client.sendall(page)
            client.close()
    except OSError as e:
        print("Request error:", e)
        try:
            client.close()
        except OSError:
            pass


PORTAL_TIMEOUT_S = 300  # give up and reboot back to normal operation if
                         # nobody completes setup in this long - important
                         # once this can be triggered remotely via MQTT,
                         # where nobody may be able to reach the AP quickly


def _dns_reply(data, ip):
    """Minimal DNS response pointing every query at `ip` - this is what
    makes a phone auto-open the setup page (captive portal behavior)
    instead of requiring the IP to be typed in manually."""
    packet = data[:2] + b"\x81\x80"
    packet += data[4:6] * 2          # QDCOUNT -> also used as ANCOUNT
    packet += b"\x00\x00\x00\x00"    # NSCOUNT, ARCOUNT
    packet += data[12:]              # echo the original question
    packet += b"\xc0\x0c"            # pointer to name in question
    packet += b"\x00\x01\x00\x01"    # TYPE A, CLASS IN
    packet += b"\x00\x00\x00\x3c"    # TTL 60s
    packet += b"\x00\x04"
    packet += bytes(int(x) for x in ip.split("."))
    return packet


def run_setup_portal(mode="full", wdt=None):
    """mode: "full" for first-time setup (WiFi + tank dimensions), or
    "add_network" to add/manage saved WiFi networks on an already
    configured device.

    wdt: optional active WDT instance - if provided, it's fed periodically
    so this function can run safely even after the watchdog has started.

    Always ends in machine.reset() - either after a successful save, or
    after PORTAL_TIMEOUT_S with nothing saved, to resume normal operation
    with whatever config already existed."""
    print("Scanning for nearby WiFi networks...")
    networks = _scan_networks()
    print("Found {} network(s)".format(len(networks)))

    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=AP_SSID, password=AP_PASSWORD, authmode=3)

    while not ap.active():
        time.sleep(0.1)

    ip = ap.ifconfig()[0]
    print("Setup AP active: '{}' (password: {})".format(AP_SSID, AP_PASSWORD))
    print("Browse to: http://{}".format(ip))
    status_led.set_status(status_led.STATUS_AWAITING_SETUP)

    if mode == "add_network":
        display.show("Add Network", "WiFi: " + AP_SSID, "Pass: " + AP_PASSWORD, "Browse to:", ip)
    else:
        display.show("Setup Mode", "WiFi: " + AP_SSID, "Pass: " + AP_PASSWORD, "Browse to:", ip)

    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.setblocking(False)
    dns_ok = True
    try:
        dns.bind(("0.0.0.0", 53))
    except OSError as e:
        print("Could not start captive-portal DNS responder (setup still works via manual IP):", e)
        dns_ok = False

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", 80))
    s.listen(5)
    s.settimeout(1.0)  # lets the loop periodically feed the watchdog

    start = time.time()

    while True:
        if wdt:
            wdt.feed()

        if time.time() - start >= PORTAL_TIMEOUT_S:
            print("Setup portal timed out after {}s with nothing saved - rebooting.".format(PORTAL_TIMEOUT_S))
            break

        if dns_ok:
            try:
                data, addr = dns.recvfrom(512)
                dns.sendto(_dns_reply(data, ip), addr)
            except OSError:
                pass

        try:
            client, addr = s.accept()
        except OSError:
            continue  # accept() timed out - no connection yet, loop back
        _handle_request(client, mode, networks)

    s.close()
    dns.close()
    ap.active(False)
    machine.reset()
