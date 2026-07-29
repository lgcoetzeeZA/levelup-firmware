from machine import Pin
import time


class Button:
    def __init__(self, pin_num, pull=Pin.PULL_DOWN):
        self.pin = Pin(pin_num, Pin.IN, pull)
        self._press_start = None
        self._hold_triggered = False

    def pressed(self):
        return self.pin.value() == 1

    def check_hold(self, hold_ms):
        """Non-blocking hold detection. Call this once per main loop
        iteration. Returns True exactly once when the button has been held
        for hold_ms milliseconds - it won't fire again until the button is
        released and pressed again."""
        if self.pressed():
            if self._press_start is None:
                self._press_start = time.ticks_ms()
                self._hold_triggered = False
            elif not self._hold_triggered and time.ticks_diff(time.ticks_ms(), self._press_start) >= hold_ms:
                self._hold_triggered = True
                return True
        else:
            self._press_start = None
            self._hold_triggered = False
        return False
