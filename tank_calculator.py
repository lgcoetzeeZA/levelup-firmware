import math


def geometric_capacity_liters(height_cm, diameter_cm):
    """Capacity of a cylindrical tank calculated purely from its dimensions."""
    radius_cm = diameter_cm / 2
    volume_cm3 = math.pi * (radius_cm ** 2) * height_cm
    return volume_cm3 / 1000.0  # 1000 cm^3 = 1 liter


def capacity_mismatch_warning(config, threshold_percent=15):
    """Returns a warning string if the entered rated capacity differs
    significantly from what the entered dimensions geometrically imply -
    useful right after setup to catch a typo in height/diameter/liters."""
    height = config.get("tank_height", 0)
    diameter = config.get("tank_diameter", 0)
    rated = config.get("tank_liters", 0)

    if height <= 0 or diameter <= 0 or rated <= 0:
        return None

    geo = geometric_capacity_liters(height, diameter)
    if geo <= 0:
        return None

    diff_percent = abs(geo - rated) / geo * 100
    if diff_percent > threshold_percent:
        return "Entered capacity ({} L) differs from calculated ({:.0f} L) by {:.0f}%. Check dimensions.".format(
            rated, geo, diff_percent
        )
    return None


def calculate_level(distance_cm, config):
    """
    distance_cm: measured distance from the sensor (mounted at the top,
                 facing down) to the water surface.
    config: dict with tank_height, tank_diameter, tank_liters (rated capacity).

    Returns a dict, or None if the config/reading isn't usable:
      percent                    - fill percentage (0-100), from geometry + sensor
      water_height_cm            - calculated depth of water
      available_liters           - liters available, scaled to rated capacity
      capacity_liters            - the capacity used for the liters figure above
      geometric_capacity_liters  - capacity calculated purely from dimensions
    """
    height = config.get("tank_height", 0)
    diameter = config.get("tank_diameter", 0)
    rated_capacity = config.get("tank_liters", 0)

    if height <= 0 or diameter <= 0:
        return None

    if distance_cm is None:
        return None

    water_height_cm = height - distance_cm
    # Clamp - a sensor glitch shouldn't report negative water or an overflow
    if water_height_cm < 0:
        water_height_cm = 0
    if water_height_cm > height:
        water_height_cm = height

    geo_capacity = geometric_capacity_liters(height, diameter)
    if geo_capacity <= 0:
        return None

    percent = (water_height_cm / height) * 100
    if percent > 100:
        percent = 100
    if percent < 0:
        percent = 0

    # Scale available liters to the rated capacity where the user provided one,
    # so the figure matches the label on the tank rather than a pure geometric
    # estimate (real tanks aren't perfect cylinders).
    display_capacity = rated_capacity if rated_capacity > 0 else geo_capacity
    available_liters = (percent / 100) * display_capacity

    return {
        "percent": round(percent, 1),
        "water_height_cm": round(water_height_cm, 1),
        "available_liters": round(available_liters, 1),
        "capacity_liters": round(display_capacity, 1),
        "geometric_capacity_liters": round(geo_capacity, 1),
    }
