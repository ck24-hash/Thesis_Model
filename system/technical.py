"""The technical side of a run, before its money: each piece of equipment at its size (how the size was found, what one
more unit costs per year, how hard it works over the year) and the year's energy flows with the demand met. From the
run's year at the chosen sizes (no solve).

Why the optimisation stops at a size: it adds capacity while one more unit (kW, kWh) saves more per year than its own
yearly cost (investment / life + fixed O&M; the battery: first purchase after subsidy and replacements over the PV life,
less its ancillary revenue). "At full size" is how often the equipment runs at its limit: a size set by the peak runs
there only a few hours a year.
"""
from __future__ import annotations

import pandas as pd

from system import flows, joint
from system.setup import System

FULL = 0.99   # share of the size that counts as running at full size


def unit_cost(s: System, block: str, size: float) -> float | None:
    """The yearly cost of one more unit of size: per kW of heat (boiler, heat pump), per kWh (heat storage, battery
    bought), at the size chosen (the battery's price tiers)."""
    c = s.commercial
    if block == "ng_boiler":
        return c.capex["boiler_per_kw_th"] / c.boiler_life_yr + c.capex["boiler_fixed_om_per_kw_year"]
    if block == "heat_pump":
        return c.heat_pump_capex(1.0) / c.heat_pump_life_yr + c.heat_pump_fixed_om(1.0)
    if block == "thermal_storage":
        return (c.capex["thermal_storage_per_kwh"] / c.thermal_storage_life_yr
                + c.capex["thermal_storage_fixed_om_per_kwh_year"])
    if block == "battery":
        terms = joint.battery_terms(s, max(size, 1.0))
        return terms["cost"] - terms["ancillary"]
    return None


def equipment(s: System, res: pd.DataFrame, heat: pd.DataFrame | None, sizes: dict, plan: dict) -> list[dict]:
    """One row per piece of equipment: size and how it was found, the yearly cost of one more unit, the energy it gives
    over the year and its share of the demand, its full-load hours (cycles for storage), the hours at full size."""
    dt, rows = s.dt, []

    def how(b):
        if b not in plan:
            return "given"
        if plan[b] is not None:
            return "fixed in the case"
        return "optimised" if sizes.get(b) else "optimised: not worth installing"

    def hours(mask):
        return float(mask.sum() * dt)

    if s.voltiris is not None and s.modules:
        volt = s.volt_pv.reindex(res.index)
        on_site = s.bm.volt_share.reindex(res.index) * (s.pv_total.reindex(res.index) - res["grid_export"]).clip(lower=0)
        rows.append({"block": "voltiris", "name": "Voltiris", "size": s.modules, "unit": "modules", "how": "given",
                     "kwp": s.modules * s.voltiris.module_wp / 1000, "output_mwh": float(volt.sum() * dt / 1000),
                     "output": "electricity produced",
                     "share_pct": float(on_site.sum() / volt.sum() * 100) if volt.sum() > 0 else None,
                     "share": "used on site"})
    if s.existing is not None:
        rows.append({"block": "existing_pv", "name": "Existing PV", "size": None, "unit": "", "how": "given (sunk)",
                     "output_mwh": float(s.existing.sum() * dt / 1000), "output": "electricity produced"})
    demand = float(heat["heat_demand"].sum()) if heat is not None else 0.0
    for b, name, col in (("ng_boiler", "Gas boiler", "boiler_heat"), ("heat_pump", "Heat pump", "hp_heat")):
        if b not in plan:
            continue
        size, given = sizes.get(b) or 0.0, heat[col] if heat is not None else pd.Series(0.0, index=res.index)
        row = {"block": b, "name": name, "size": size, "unit": "kW of heat", "how": how(b),
               "unit_cost_yr": unit_cost(s, b, size), "unit_cost": "per kW of heat per year",
               "output_mwh": float(given.sum() * dt / 1000), "output": "heat given",
               "share_pct": float(given.sum() / demand * 100) if demand > 0 else None, "share": "of the heat demand",
               "full_load_h": float(given.sum() * dt / size) if size else None,
               "at_full_h": hours(given >= FULL * size) if size else None}
        if b == "heat_pump" and heat is not None and heat["hp_electricity"].sum() > 0:
            row["spf"] = float(heat["hp_heat"].sum() / heat["hp_electricity"].sum())
            row["electricity_mwh"] = float(heat["hp_electricity"].sum() * dt / 1000)
        rows.append(row)
    if "thermal_storage" in plan:
        size = sizes.get("thermal_storage") or 0.0
        out = heat["storage_discharge"] if heat is not None and "storage_discharge" in heat else None
        rows.append({"block": "thermal_storage", "name": "Heat storage", "size": size, "unit": "kWh of heat",
                     "how": how("thermal_storage"), "unit_cost_yr": unit_cost(s, "thermal_storage", size),
                     "unit_cost": "per kWh per year", "power_kw": s.storage.power_kw(size) if size else None,
                     "output_mwh": float(out.sum() * dt / 1000) if out is not None else 0.0, "output": "heat given back",
                     "share_pct": float(out.sum() / demand * 100) if out is not None and demand > 0 else None,
                     "share": "of the heat demand",
                     "cycles": float(out.sum() * dt / size) if out is not None and size else None,
                     "at_full_h": hours(heat["storage_soc"] >= FULL * size) if out is not None and size else None,
                     "at_full": "full"})
    if "battery" in plan:
        size = sizes.get("battery") or 0.0
        has = "battery_power" in res and size
        out = res["battery_power"].clip(lower=0) if has else None
        power = s.battery.tech.dispatch_kw(size) if size else 0.0
        rows.append({"block": "battery", "name": "Battery", "size": size, "unit": "kWh bought", "how": how("battery"),
                     "unit_cost_yr": unit_cost(s, "battery", size), "unit_cost": "per kWh bought per year",
                     "power_kw": power or None, "usable_kwh": s.battery.tech.dispatch_kwh(size) if size else None,
                     "output_mwh": float(out.sum() * dt / 1000) if has else 0.0, "output": "electricity given back",
                     "share_pct": float(out.sum() / res["load"].sum() * 100) if has else None,
                     "share": "of the load",
                     "cycles": float(out.sum() * dt / size) if has else None,
                     "at_full_h": hours(res["battery_power"].abs() >= FULL * power) if has and power else None,
                     "at_full": "at full power"})
    if s.external_co2 is not None and heat is not None:
        co2 = float(heat["co2_demand"].sum())
        rows.append({"block": "external_co2", "name": "External CO2", "size": None, "unit": "", "how": "given",
                     "output_mwh": float(heat["co2_bought"].sum() * dt / 1000), "output": "t of CO2 bought",
                     "share_pct": float(heat["co2_bought"].sum() / co2 * 100) if co2 > 0 else None,
                     "share": "of the CO2 demand"})
    return rows


def energy(s: System, res: pd.DataFrame, heat: pd.DataFrame | None) -> list[dict]:
    """The year's energy flows and the demand met: [{"carrier", "item", "value", "unit"}]."""
    dt = s.dt

    def mwh(x):
        return float(x.sum() * dt / 1000)
    sc = flows.sc_ss(res, s)
    rows = [("Electricity", "Greenhouse load", mwh(res["greenhouse_load"] if "greenhouse_load" in res else res["load"]), "MWh")]
    if "heat_pump" in res:
        rows.append(("Electricity", "Heat pump draw", mwh(res["heat_pump"]), "MWh"))
    rows += [("Electricity", "PV produced", mwh(res["pv"]), "MWh"),
             ("Electricity", "Self-consumption (PV used on site)", sc["sc_pct"], "%"),
             ("Electricity", "Self-sufficiency (load met by PV)", sc["ss_pct"], "%"),
             ("Electricity", "Grid import", mwh(res["grid_import"]), "MWh"),
             ("Electricity", "Grid export", mwh(res["grid_export"]), "MWh"),
             ("Electricity", "Highest import", float(res["grid_import"].max()), "kW")]
    if heat is not None and heat["heat_demand"].sum() > 0:
        rows += [("Heat", "Heat demand", mwh(heat["heat_demand"]), "MWh"),
                 ("Heat", "From the gas boiler", mwh(heat["boiler_heat"]), "MWh"),
                 ("Heat", "From the heat pump", mwh(heat["hp_heat"]), "MWh")]
        if "storage_discharge" in heat:
            rows.append(("Heat", "Through the heat storage", mwh(heat["storage_discharge"]), "MWh"))
        rows += [("Heat", "Released (not needed)", mwh(heat["heat_release"]), "MWh"),
                 ("Heat", "Unmet", mwh(heat["heat_unmet"]), "MWh")]
    if heat is not None and heat["co2_demand"].sum() > 0:
        rows += [("CO2", "CO2 demand", mwh(heat["co2_demand"]), "t"),
                 ("CO2", "From the boiler's flue gas", mwh((heat["co2_supplied"] - heat["co2_bought"]).clip(lower=0)), "t"),
                 ("CO2", "Bought", mwh(heat["co2_bought"]), "t"),
                 ("CO2", "Vented", mwh(heat["co2_vented"]), "t"),
                 ("CO2", "Unmet", mwh(heat["co2_unmet"]), "t")]
    if heat is not None and heat["gas"].sum() > 0:
        rows += [("Gas", "Gas burnt", mwh(heat["gas"]), "MWh"),
                 ("Gas", "CO2 emitted by the gas", mwh(heat["co2_emitted"]), "t")]
    return [{"carrier": c, "item": i, "value": v, "unit": u} for c, i, v, u in rows]
