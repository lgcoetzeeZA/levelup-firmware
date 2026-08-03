import time
from machine import Pin
import ultrasonic_sensor
import tank_calculator

TRIG_PIN = 26
ECHO_PIN = 27

DIP1_PIN = 14
DIP2_PIN = 13

# Standard/previous ultrasonic sensor (e.g. HC-SR04-style) plausible range
STANDARD_SENSOR_MIN_CM = 2
STANDARD_SENSOR_MAX_CM = 400

# AJ-SR04M (waterproof) - measured blind zone and datasheet max range
AJ_SR04M_MIN_CM = 21
AJ_SR04M_MAX_CM = 450

SAMPLE_COUNT = 5             # readings taken per measurement cycle
SAMPLE_DELAY_MS = 20         # gap between samples within one cycle
ERROR_THRESHOLD = 10         # consecutive failed cycles before "error" (vs "stale")
SMOOTHING_ALPHA = 0.3        # cross-cycle smoothing - lower = smoother but slower to react
MAX_STALE_SECONDS = 300      # force "error" if no good reading in this long, even if
                              # consecutive_failures hasn't hit ERROR_THRESHOLD (e.g. the
                              # sensor is intermittently succeeding just often enough to
                              # keep resetting that counter without ever being reliable)
MAX_CHANGE_CM_PER_CYCLE = 15  # reject a reading that implies the water level jumped by
                               # more than this between cycles (~5s apart) - catches a
                               # persistent false echo that fools the within-cycle median,
                               # since a real reservoir can't physically move this fast

_dip1 = Pin(DIP1_PIN, Pin.IN, Pin.PULL_DOWN)
_dip2 = Pin(DIP2_PIN, Pin.IN, Pin.PULL_DOWN)


def _select_sensor_range():
    """Reads the dip switches once at boot to determine which sensor is
    fitted:
      1 ON  + 2 ON  -> AJ-SR04M (waterproof)
      1 OFF + 2 OFF -> standard/previous sensor
      any other combo -> falls back to the standard sensor range, since
      1 ON + 2 OFF is reserved for arming the Left button's OTA shortcut,
      not a sensor selection."""
    d1 = _dip1.value()
    d2 = _dip2.value()

    if d1 == 1 and d2 == 1:
        print("Sensor type: AJ-SR04M (waterproof) - dip switches 1+2 ON")
        return "AJ-SR04M", AJ_SR04M_MIN_CM, AJ_SR04M_MAX_CM

    if d1 == 0 and d2 == 0:
        print("Sensor type: standard sensor - dip switches 1+2 OFF")
        return "Standard", STANDARD_SENSOR_MIN_CM, STANDARD_SENSOR_MAX_CM

    print("Dip switches don't match a defined sensor combo - defaulting to standard sensor range")
    return "Standard", STANDARD_SENSOR_MIN_CM, STANDARD_SENSOR_MAX_CM


_sensor_type_label, _min_cm, _max_cm = _select_sensor_range()
_sensor = ultrasonic_sensor.UltrasonicSensor(TRIG_PIN, ECHO_PIN, timeout_us=30000,
                                              min_plausible_cm=_min_cm, max_plausible_cm=_max_cm)

_last_good_distance = None
_last_good_level = None
_last_good_time = None
_consecutive_failures = 0
_smoothed_distance = None


def get_sensor_type():
    """Returns the sensor type label selected at boot, e.g. for MQTT visibility."""
    return _sensor_type_label


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
    global _last_good_distance, _last_good_level, _last_good_time, _consecutive_failures, _smoothed_distance

    distance = _sample_distance()

    if distance is not None and _last_good_distance is not None:
        implied_change = abs(distance - _last_good_distance)
        if implied_change > MAX_CHANGE_CM_PER_CYCLE:
            print("Rejecting implausible reading: {}cm (previous good: {}cm, jump: {}cm)".format(
                distance, round(_last_good_distance, 1), round(implied_change, 1)
            ))
            distance = None

    if distance is not None:
        if _consecutive_failures >= ERROR_THRESHOLD:
            # Sensor was in a hard error state for a while - don't blend this
            # recovery reading with a now-stale anchor, just start fresh.
            _smoothed_distance = None

        if _smoothed_distance is None:
            _smoothed_distance = distance
        else:
            _smoothed_distance = SMOOTHING_ALPHA * distance + (1 - SMOOTHING_ALPHA) * _smoothed_distance

        _consecutive_failures = 0
        _last_good_distance = _smoothed_distance
        _last_good_time = time.time()
        level = tank_calculator.calculate_level(_smoothed_distance, config)
        _last_good_level = level
        return {
            "status": "ok",
            "distance_cm": round(_smoothed_distance, 1),
            "consecutive_failures": 0,
            "seconds_since_good": 0,
            "level": level,
        }

    _consecutive_failures += 1

    if _last_good_distance is None:
        return {
            "status": "error",
            "distance_cm": None,
            "consecutive_failures": _consecutive_failures,
            "seconds_since_good": None,
            "level": None,
        }

    seconds_since_good = time.time() - _last_good_time

    if _consecutive_failures >= ERROR_THRESHOLD or seconds_since_good >= MAX_STALE_SECONDS:
        status = "error"
    else:
        status = "stale"

    return {
        "status": status,
        "distance_cm": round(_last_good_distance, 1),
        "consecutive_failures": _consecutive_failures,
        "seconds_since_good": seconds_since_good,
        "level": _last_good_level,
    }
