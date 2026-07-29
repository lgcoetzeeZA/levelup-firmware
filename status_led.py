from machine import Pin, Timer

_OFF = "off"
_ON = "on"
_SLOW = "slow_blink"
_FAST = "fast_blink"

# Public status names - use these from main.py / setup_portal.py
STATUS_NOT_CONFIGURED = "not_configured"   # no settings saved yet
STATUS_AWAITING_SETUP = "awaiting_setup"   # AP live, waiting for phone
STATUS_SAVED = "saved"                     # settings just saved, about to reboot
STATUS_CONNECTING = "connecting"           # attempting to join saved WiFi
STATUS_CONNECTED = "connected"             # WiFi connected, all good
STATUS_WIFI_FAILED = "wifi_failed"         # saved WiFi didn't work
STATUS_MQTT_FAILED = "mqtt_failed"         # WiFi is fine, but MQTT/broker isn't

# Maps each status to (wifi_led_mode, system_led_mode)
_STATUS_MAP = {
    STATUS_NOT_CONFIGURED: (_OFF, _FAST),
    STATUS_AWAITING_SETUP: (_OFF, _SLOW),
    STATUS_SAVED: (_ON, _ON),
    STATUS_CONNECTING: (_FAST, _OFF),
    STATUS_CONNECTED: (_ON, _ON),
    STATUS_WIFI_FAILED: (_FAST, _FAST),
    STATUS_MQTT_FAILED: (_ON, _FAST),
}


class _StatusLED:
    def __init__(self, pin_num):
        self.pin = Pin(pin_num, Pin.OUT)
        self.pin.value(0)
        self.timer = Timer(-1)
        self._mode = _OFF

    def set_mode(self, mode):
        if mode == self._mode:
            return
        self._mode = mode
        self.timer.deinit()

        if mode == _OFF:
            self.pin.value(0)
        elif mode == _ON:
            self.pin.value(1)
        elif mode == _SLOW:
            self.pin.value(0)
            self.timer.init(period=800, mode=Timer.PERIODIC, callback=self._toggle)
        elif mode == _FAST:
            self.pin.value(0)
            self.timer.init(period=150, mode=Timer.PERIODIC, callback=self._toggle)

    def _toggle(self, t):
        self.pin.value(not self.pin.value())


_wifi_led = _StatusLED(19)
_sys_led = _StatusLED(18)


def set_status(status):
    """Set both LEDs according to a named device status (see STATUS_* constants)."""
    if status not in _STATUS_MAP:
        print("Unknown status:", status)
        return
    wifi_mode, sys_mode = _STATUS_MAP[status]
    _wifi_led.set_mode(wifi_mode)
    _sys_led.set_mode(sys_mode)
