from machine import Pin, SoftI2C
import framebuf

_oled = None
_available = False


def _init():
    global _oled, _available
    try:
        import ssd1306
        i2c = SoftI2C(scl=Pin(22), sda=Pin(21))
        _oled = ssd1306.SSD1306_I2C(128, 64, i2c)
        _available = True
        print("OLED display detected.")
    except Exception as e:
        _available = False
        print("No OLED display detected - continuing without screen.")


_init()


def available():
    return _available


def show(*lines):
    """Display up to 5 lines of text (10px row height fits 128x64).
    Does nothing if no screen was detected at startup."""
    if not _available:
        return
    try:
        _oled.fill(0)
        y = 0
        for line in lines[:5]:
            _oled.text(str(line), 0, y)
            y += 10
        _oled.show()
    except OSError:
        # Screen may have been unplugged mid-run - fail silently rather
        # than crashing the whole device over a display glitch.
        pass


def clear():
    if not _available:
        return
    try:
        _oled.fill(0)
        _oled.show()
    except OSError:
        pass


def _scaled_text(text, x, y, scale):
    """Draws text scaled up by an integer factor. Renders into a small
    offscreen buffer using the built-in 8x8 font, then blits each 'on'
    pixel as a scale x scale block onto the real display - reuses the
    built-in font rather than needing a separate large-digit font."""
    if scale <= 1:
        _oled.text(text, x, y)
        return
    w = 8 * len(text)
    h = 8
    buf = bytearray(w * ((h + 7) // 8))
    fbuf = framebuf.FrameBuffer(buf, w, h, framebuf.MONO_VLSB)
    fbuf.fill(0)
    fbuf.text(text, 0, 0, 1)
    for ty in range(h):
        for tx in range(w):
            if fbuf.pixel(tx, ty):
                _oled.fill_rect(x + tx * scale, y + ty * scale, scale, scale, 1)


def _wifi_bars(x, y, signal_percent):
    """4-bar WiFi signal strength icon, like a phone's signal indicator."""
    bar_w = 2
    gap = 1
    heights = (3, 5, 7, 9)

    if signal_percent is None:
        lit = 0
    elif signal_percent >= 75:
        lit = 4
    elif signal_percent >= 50:
        lit = 3
    elif signal_percent >= 25:
        lit = 2
    elif signal_percent > 0:
        lit = 1
    else:
        lit = 0

    base_y = y + 10
    for i, bar_h in enumerate(heights):
        bx = x + i * (bar_w + gap)
        by = base_y - bar_h
        if i < lit:
            _oled.fill_rect(bx, by, bar_w, bar_h, 1)
        else:
            _oled.rect(bx, by, bar_w, bar_h, 1)


def _status_square(x, y, state):
    """state: 'on' (filled), 'off' (hollow), or 'error' (hollow + X)."""
    size = 8
    if state == "on":
        _oled.fill_rect(x, y, size, size, 1)
    else:
        _oled.rect(x, y, size, size, 1)
        if state == "error":
            _oled.line(x, y, x + size - 1, y + size - 1, 1)
            _oled.line(x, y + size - 1, x + size - 1, y, 1)


def show_dashboard(percent, available_liters, capacity_liters, wifi_signal_percent, mqtt_connected, sensor_status, relay_on):
    """Main operational status screen: a top icon row (WiFi / MQTT / Sensor /
    Relay), a large hero percentage, and a bottom summary line. Does nothing
    if no screen was detected at startup."""
    if not _available:
        return
    try:
        _oled.fill(0)

        _wifi_bars(2, 2, wifi_signal_percent)

        _status_square(34, 2, "on" if mqtt_connected else "off")
        _oled.text("M", 44, 2)

        if sensor_status == "ok":
            sensor_state = "on"
        elif sensor_status == "stale":
            sensor_state = "off"
        else:
            sensor_state = "error"
        _status_square(60, 2, sensor_state)
        _oled.text("S", 70, 2)

        _status_square(86, 2, "on" if relay_on else "off")
        _oled.text("R", 96, 2)

        if percent is None:
            hero = "--"
        else:
            hero = "{:.0f}%".format(percent)
        hero_w = 8 * 3 * len(hero)
        hero_x = max(0, (128 - hero_w) // 2)
        _scaled_text(hero, hero_x, 18, 3)

        if percent is not None and available_liters is not None:
            summary = "{:.0f}/{:.0f} L".format(available_liters, capacity_liters)
        else:
            summary = "No reading yet"
        summary_x = max(0, (128 - 8 * len(summary)) // 2)
        _oled.text(summary, summary_x, 54)

        _oled.show()
    except OSError:
        pass
