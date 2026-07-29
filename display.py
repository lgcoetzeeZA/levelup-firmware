from machine import Pin, SoftI2C

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
