"""
Wrapper around the third-party vl53l1x.py driver (sourced separately -
see setup instructions), matching the same read_raw() interface as
ultrasonic_sensor.py so it can be dropped into reservoir_sensor.py's
sensor-type selection without changing anything else.
"""

from machine import Pin, SoftI2C
from vl53l1x import VL53L1X

SCL_PIN = 22
SDA_PIN = 21


class ToFSensor:
    def __init__(self, scl_pin=SCL_PIN, sda_pin=SDA_PIN, min_plausible_cm=4, max_plausible_cm=300):
        self.min_plausible_cm = min_plausible_cm
        self.max_plausible_cm = max_plausible_cm
        self._sensor = None
        self._available = False
        try:
            i2c = SoftI2C(scl=Pin(scl_pin), sda=Pin(sda_pin))
            self._sensor = VL53L1X(i2c)
            self._available = True
            print("VL53L1X ToF sensor detected.")
        except (OSError, RuntimeError) as e:
            print("VL53L1X not detected - check wiring:", e)

    def read_raw(self):
        """Single distance reading in cm, or None if the sensor isn't
        present or the reading is implausible."""
        if not self._available:
            return None
        try:
            distance_mm = self._sensor.read()
        except OSError:
            return None

        distance_cm = distance_mm / 10.0

        if distance_cm < self.min_plausible_cm or distance_cm > self.max_plausible_cm:
            return None

        return distance_cm
