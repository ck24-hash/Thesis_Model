"""Investment: the battery price by size (tiers), the PV price, and battery replacements over the PV life."""
from __future__ import annotations

import numpy as np


def battery_price_per_kwh(size_kwh: float, capex: dict) -> float:
    """Price per kWh at this size, linear between the tiers (and flat beyond the first and last)."""
    tiers = capex["battery_tiers_per_kwh"]
    return float(np.interp(size_kwh, [t[0] for t in tiers], [t[1] for t in tiers]))


def battery_gross(size_kwh: float, capex: dict) -> float:
    return size_kwh * battery_price_per_kwh(size_kwh, capex)


def pv_gross(modules: int, module_wp: float, capex: dict) -> float:
    return modules * module_wp * capex["pv_per_wp"]


def battery_replacements(pv_life_yr: float, battery_life_yr: float) -> float:
    """How many times the battery is bought again within the PV life (may be fractional)."""
    return pv_life_yr / battery_life_yr - 1


def battery_replacement_cost(size_kwh: float, capex: dict, pv_life_yr: float, battery_life_yr: float) -> float:
    """All replacements over the PV life, each at battery_replacement_frac of the gross price, unsubsidised."""
    return (battery_replacements(pv_life_yr, battery_life_yr) * capex["battery_replacement_frac"]
            * battery_gross(size_kwh, capex))
