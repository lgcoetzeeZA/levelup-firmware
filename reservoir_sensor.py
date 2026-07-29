import time
import ultrasonic_sensor
import tank_calculator

TRIG_PIN = 26
ECHO_PIN = 27

SAMPLE_COUNT = 5             # readings taken per measurement cycle
SAMPLE_DELAY_MS = 20         # gap between samples within one cycle
ERROR_THRESHOLD = 10         # consecutive failed cycles before "error" (vs "stale")

_sensor = ultrasonic_sensor.UltrasonicSensor(TRIG_PIN, ECHO_PIN, timeout_us=30000)

_last_good_distance = None
_last_good_level = None
_consecutive_failures = 0


def _median(values):
    values = sorted(values)
    n = len(values)
    mid = n // 2
    if n % 2 == 0:
        return (values[mid - 1] + values[mid]) / 2
    return values[mid]


def _sample_distance():
    """Take several raw readings and return the median of the successful
    ones - a single splash/glitch reading won't skew the result the way
    an average would. Returns None only if every sample in the batch failed."""
    readings = []
    for _ in range(SAMPLE_COUNT):
        d = _sensor.read_raw()
        if d is not None:
            readings.append(d)
        time.sleep_ms(SAMPLE_DELAY_MS)

    if not readings:
        return None

    return _median(readings)


def read(config):
    """Take a tank level reading. Always returns a dict, never None, so
    callers (display, MQTT, relay logic) never need to special-case a
    missing reading.

    Returns:
      status                - "ok", "stale", or "error"
                               ok    = fresh good reading this cycle
                               stale = sensor failed this cycle, but we have
                                       a recent good reading to fall back on
                               error = sensor failed and either it's been
                                       failing for a while, or we've never
                                       had a good reading since boot
      distance_cm           - last known distance (fresh or held over), or None
      consecutive_failures  - how many read cycles in a row have failed
      level                 - tank_calculator.calculate_level() dict, or None
                               if there has never been a good reading
    """
    global _last_good_distance, _last_good_level, _consecutive_failures

    distance = _sample_distance()

    if distance is not None:
        _consecutive_failures = 0
        _last_good_distance = distance
        level = tank_calculator.calculate_level(distance, config)
        _last_good_level = level
        return {
            "status": "ok",
            "distance_cm": round(distance, 1),
            "consecutive_failures": 0,
            "level": level,
        }

    _consecutive_failures += 1

    if _last_good_distance is None:
        return {
            "status": "error",
            "distance_cm": None,
            "consecutive_failures": _consecutive_failures,
            "level": None,
        }

    status = "error" if _consecutive_failures >= ERROR_THRESHOLD else "stale"

    return {
        "status": status,
        "distance_cm": round(_last_good_distance, 1),
        "consecutive_failures": _consecutive_failures,
        "level": _last_good_level,
    }
