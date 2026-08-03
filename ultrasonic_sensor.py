import machine
from machine import Pin
import time


class UltrasonicSensor:
    def __init__(self, trig_pin, echo_pin, timeout_us=30000, min_plausible_cm=21, max_plausible_cm=450):
        self.trig = Pin(trig_pin, Pin.OUT)
        self.echo = Pin(echo_pin, Pin.IN)
        self.timeout_us = timeout_us
        self.min_plausible_cm = min_plausible_cm
        self.max_plausible_cm = max_plausible_cm
        self.trig.value(0)

    def read_raw(self):
        """Take a single raw distance reading in cm.
        Returns None if the sensor timed out or the reading is implausible."""
        self.trig.value(0)
        time.sleep_us(2)
        self.trig.value(1)
        time.sleep_us(10)
        self.trig.value(0)

        try:
            duration = machine.time_pulse_us(self.echo, 1, self.timeout_us)
        except OSError:
            return None

        if duration < 0:
            return None  # timed out waiting for the echo

        distance_cm = duration / 58.0

        if distance_cm < self.min_plausible_cm or distance_cm > self.max_plausible_cm:
            return None  # below the sensor's blind zone, or beyond its rated range

        return distance_cm
