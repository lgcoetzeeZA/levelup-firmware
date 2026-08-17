"""
Tank level/volume calculation - matches LevelMicro's math exactly.

Percentage and volume are both derived purely from tank geometry (height +
diameter) and the measured distance. There is no separate "rated capacity"
override - a real tank's capacity is whatever its actual dimensions say it
is, computed the same way every time.

    sensor
      |
      | sensor_offset_cm   <- gap between sensor and the full/overflow line
      |
    ==+== full/overflow line (100% - water above this just spills out)
      |
      | tank_height_cm     <- usable fill height, bottom to overflow
      |
    __|__ tank bottom (0%)

  tank_roof_cm = sensor_offset_cm + tank_height_cm
               = distance the sensor reads when the tank is completely empty
"""

import math


def tank_roof_cm(config):
    """Sensor reading when the tank is completely empty (0%)."""
    return config.get("sensor_offset_cm", 0) + config.get("tank_height", 0)


def calculate_level(distance_cm, config):
    """
    distance_cm: measured distance from the sensor (mounted at the top,
                 facing down) to the water surface.
    config: dict with tank_height, tank_diameter, sensor_offset_cm, and
            tank_count (identical tanks connected in series, sharing one
            water level - default 1).

    Returns a dict, or None if the config/reading isn't usable:
      percent        - fill percentage (0-100) - a ratio, unaffected by
                       tank_count since all connected tanks share one level
      water_cm       - depth of water, in cm (single tank's depth)
      volume_l       - liters currently available, across all connected tanks
      tank_volume_l  - total capacity (at 100%), across all connected tanks
    """
    height = config.get("tank_height", 0)
    diameter = config.get("tank_diameter", 0)
    tank_count = config.get("tank_count", 1) or 1

    if height <= 0 or diameter <= 0:
        return None
    if distance_cm is None:
        return None

    roof_cm = tank_roof_cm(config)

    water_cm = roof_cm - distance_cm
    water_cm = max(0.0, min(water_cm, float(height)))

    percent = round(100.0 * water_cm / height, 1) if height > 0 else 0.0

    radius_m = (diameter / 2.0) / 100.0
    single_volume_l = math.pi * radius_m * radius_m * (water_cm / 100.0) * 1000.0
    single_tank_volume_l = math.pi * radius_m * radius_m * (height / 100.0) * 1000.0

    volume_l = round(single_volume_l * tank_count, 1)
    tank_volume_l = round(single_tank_volume_l * tank_count, 1)

    return {
        "percent": percent,
        "water_cm": round(water_cm, 1),
        "volume_l": volume_l,
        "tank_volume_l": tank_volume_l,
    }
