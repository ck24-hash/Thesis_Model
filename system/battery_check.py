"""A check of the battery's joint size: the battery sized again by the reference model's sweep (elements/battery/study.py,
Jesse's rule: every size of a list solved over the year, the highest lifetime profit kept) with the other blocks at
their joint sizes, set against the joint size. Switched by the case's "system": {"battery_check": true} (default on);
off, the run skips it.

The two rules are not the same, so the sizes may differ even when both are right:
    joint sizing   the lowest yearly cost of the site, any size up to the limit; the battery's investment (first
                   purchase after subsidy, EMS hardware, replacements within the PV life) spread over the PV life
    sweep          the highest lifetime profit (yearly value x battery life - first purchase after subsidy and EMS
                   hardware) among the sizes of its list that pay back within the battery life
"""
from __future__ import annotations

from elements.battery import sizing as battery_sizing
from elements.battery import study as battery_study
from system import costs
from system.setup import System

DEFAULT = True


def enabled(case: dict) -> bool:
    return bool((case.get("system") or {}).get("battery_check", DEFAULT))


def _figures(s: System, study: dict | None, heat, sizes: dict) -> dict:
    """A battery study's key figures, with the site's yearly cost at its size."""
    if study is None:
        return {"size": 0.0}
    sm = study["summary"]
    grid = costs.grid_part(study["dispatch"], s, sm["regime_battery"])
    h = study.get("heat_dispatch") if study.get("heat_dispatch") is not None else heat
    site = costs.yearly(s, grid, h, {**sizes, "battery": sm["battery_kwh"]}, ems_yr=sm["battery_ems_yr"])
    return {"size": float(sm["battery_kwh"]), "value_yr": sm["battery_value_yr"], "investment": sm["battery_investment"],
            "payback_yr": sm["battery_payback_yr"], "lifetime_profit": sm["battery_lifetime_profit"],
            "battery_per_year": costs.battery_per_year(s, sm["battery_kwh"]), "site_yearly_cost": site["total"],
            "regime": sm["regime_battery"]}


def run(s: System, case: dict, out: dict, *, regime_auto: bool = True, regime_manual: str | None = None, tag: str = "case",
        log=print) -> dict:
    """The sweep's battery against the joint one: their figures side by side and the sweep's table."""
    log("\n=== BATTERY CHECK: THE REFERENCE SWEEP ===")
    sizes = {"ng_boiler": s.boiler_kw, "heat_pump": s.heat_pump_kw, "thermal_storage": s.storage_kwh}
    settings = {**((case["blocks"].get("battery") or {}).get("sizing") or {})}
    if settings.get("objective") == "custom":
        settings["objective"] = "profit"   # the case fixes the joint size; the sweep still picks its own
    sweep = battery_study.run(s, regime_auto=regime_auto, regime_manual=regime_manual, sizing_settings=settings,
                              tag=tag, log=log)
    heat = out.get("heat_side")
    joint = _figures(s, out["battery"], heat, sizes)
    if out["battery"] is None:   # the joint sizing left the battery out: the site's yearly cost without it
        joint["site_yearly_cost"] = out["costs"]["total"]
    ref = _figures(s, sweep, heat, sizes)
    log(f"  Joint sizing {joint['size']:,.0f} kWh, sweep {ref['size']:,.0f} kWh"
        + ("  (the same)" if abs(joint["size"] - ref["size"]) < 0.5 else ""))
    return {"joint": joint, "sweep": ref, "same": abs(joint["size"] - ref["size"]) < 0.5,
            "objective": {**battery_sizing.DEFAULTS, **settings}["objective"],
            "table": sweep["sweep"].reset_index(), "battery_life_yr": s.commercial.battery_life_yr,
            "pv_life_yr": s.pv_life_yr}
