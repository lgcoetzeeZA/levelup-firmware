from machine import Pin, Timer

OFF = "off"
ON = "on"
BLINK = "blink"


class IndicatorLED:
    def __init__(self, pin_num, blink_period_ms=500):
        self.pin = Pin(pin_num, Pin.OUT)
        self.pin.value(0)
        self.timer = Timer(-1)
        self.blink_period_ms = blink_period_ms
        self._mode = OFF

    def set_mode(self, mode):
        if mode == self._mode:
            return
        self._mode = mode
        self.timer.deinit()

        if mode == OFF:
            self.pin.value(0)
        elif mode == ON:
            self.pin.value(1)
        elif mode == BLINK:
            self.pin.value(0)
            self.timer.init(period=self.blink_period_ms, mode=Timer.PERIODIC, callback=self._toggle)

    def _toggle(self, t):
        self.pin.value(not self.pin.value())
