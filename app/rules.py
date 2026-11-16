"""Alert rules for incoming machine telemetry.

The thresholds are the failure-mode definitions published with the
AI4I 2020 Predictive Maintenance dataset (Matzka, 2020):

  TWF  tool wear failure         tool wear reaches the replacement window (>= limit, default 200 min)
  HDF  heat dissipation failure  process-air temperature gap < 8.6 K and speed < 1380 rpm
  PWF  power failure             torque x angular speed outside 3500..9000 W
  OSF  overstrain failure        tool wear x torque above 11000 / 12000 / 13000 minNm for L / M / H
"""
import math

DEFAULT_TOOL_WEAR_LIMIT = 200.0
OSF_LIMIT = {"L": 11000.0, "M": 12000.0, "H": 13000.0}


def evaluate(reading: dict, tool_wear_limit: float = DEFAULT_TOOL_WEAR_LIMIT) -> list:
    """Return a list of {"rule", "detail"} dicts for every rule the reading violates."""
    alerts = []
    wear = reading["tool_wear_min"]
    torque = reading["torque_nm"]
    rpm = reading["rpm"]
    gap = reading["process_temp_k"] - reading["air_temp_k"]
    power_w = torque * rpm * 2 * math.pi / 60.0

    if wear >= tool_wear_limit:
        alerts.append({"rule": "TWF", "detail": f"tool wear {wear:.0f} min >= limit {tool_wear_limit:.0f}"})
    if gap < 8.6 and rpm < 1380:
        alerts.append({"rule": "HDF", "detail": f"temp gap {gap:.1f} K < 8.6 and speed {rpm:.0f} rpm < 1380"})
    if power_w < 3500 or power_w > 9000:
        alerts.append({"rule": "PWF", "detail": f"power {power_w:.0f} W outside 3500..9000"})
    limit = OSF_LIMIT.get(reading.get("type", "M"), 12000.0)
    if wear * torque > limit:
        alerts.append({"rule": "OSF", "detail": f"strain {wear * torque:.0f} minNm > {limit:.0f}"})
    return alerts
