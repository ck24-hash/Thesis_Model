"""The site's yearly cost: what the grower pays in a year for the run's system at its sizes, in one table (thesis.md
section 8, money flows). Two parts:

    running     the grid bill (energy and network, capacity charges, minus the export revenue, the EaaS fee), gas,
                carbon levy, O&M of the boiler and the heat storage, the battery's EMS costs minus its ancillary
                revenue
    investment  each investment spread over its life (investment / life, no discounting: the same rule as the
                studies' lifetime profit and lifetime cost): Voltiris modules (direct sales; under EaaS the grower
                pays the fee instead), boiler, heat storage, battery with its EMS hardware

The battery's investment / battery life stands for buying it again at the end of its life, at full price (the battery
study's payback table counts replacements at a share of the price). Existing PV is sunk. Heat or CO2 demand left
unmet is reported, not priced.
"""
from __future__ import annotations

import pandas as pd

from system import flows
from system.setup import System


def grid_part(res: pd.DataFrame, s: System, regime: str) -> dict:
    """The grid bill of a dispatch, by part (the electricity side's key names)."""
    b = flows.bill(res["grid_import"], res["grid_export"], s, regime)
    dt = s.dt
    return {"import_cost": b["imp_cost"], "capacity_charges": b["demand"], "export_revenue": b["exp_rev"],
            "eaas_fee": b["eaas_fee"], "bill": b["total"], "import_mwh": float(res["grid_import"].sum() * dt / 1000),
            "export_mwh": float(res["grid_export"].sum() * dt / 1000)}


def yearly(s: System, grid: dict, heat: pd.DataFrame | None = None, sizes: dict | None = None,
           ems_yr: float | None = None, bill_without_battery: float | None = None) -> dict:
    """The site's yearly cost. grid: grid_part() or the electricity side's key figures; heat: the heat results
    (dispatch.heat_results) when the system has a heat side; sizes: {"ng_boiler": kW, "thermal_storage": kWh,
    "battery": kWh}; the battery's EMS costs: ems_yr, or from the bill without battery (its fees are a share of the
    saving)."""
    sizes = sizes or {}
    dt, c = s.dt, s.commercial
    boiler_kw, storage_kwh, battery_kwh = (sizes.get(k) or 0.0 for k in ("ng_boiler", "thermal_storage", "battery"))
    running = {
        "Grid: energy and network": grid["import_cost"],
        "Grid: capacity charges": grid["capacity_charges"],
        "Grid: export revenue": -grid["export_revenue"],
    }
    if grid.get("eaas_fee"):
        running["Voltiris EaaS fee"] = grid["eaas_fee"]
    other = {"Grid import (MWh)": grid["import_mwh"], "Grid export (MWh)": grid["export_mwh"]}
    if heat is not None:
        running["Gas"] = float((heat["gas"] * s.gas.price.reindex(heat.index) * dt).sum())
        running["Carbon levy"] = float((heat["gas"] * s.gas.levy_per_kwh * dt).sum())
        running["Boiler O&M"] = (c.boiler_fixed_om(boiler_kw)
                                 + float((heat["boiler_heat"] * c.boiler_var_om_per_kwh * dt).sum()))
        if storage_kwh:
            running["Heat storage O&M"] = c.thermal_storage_fixed_om(storage_kwh)
        other.update({"Gas (MWh)": float(heat["gas"].sum() * dt / 1000),
                      "Heat unmet (MWh)": float(heat["heat_unmet"].sum() * dt / 1000),
                      "CO2 unmet (t)": float(heat["co2_unmet"].sum() * dt / 1000),
                      "CO2 emitted (t)": float(heat["co2_emitted"].sum() * dt / 1000)})
    investment, invested = {}, {}
    if battery_kwh:
        ancillary = s.ancillary_revenue(battery_kwh)
        if ems_yr is None:
            saving = bill_without_battery - grid["bill"] if bill_without_battery is not None else 0.0
            ems_yr = s.ems.fees(ancillary, saving)["total"]
        running["Battery: EMS"] = ems_yr
        running["Battery: ancillary revenue"] = -ancillary
    if s.voltiris is not None and s.modules and not s.bm.eaas:
        gross = c.pv_capex(s.modules, s.voltiris.module_wp)
        invested["Voltiris modules"] = s.subsidies.pv_net(gross, s.modules, s.voltiris.module_wp, c.capex["pv_per_wp"])
        investment["Voltiris modules"] = invested["Voltiris modules"] / s.pv_life_yr
    if boiler_kw:
        invested["Gas boiler"] = c.boiler_capex(boiler_kw)
        investment["Gas boiler"] = invested["Gas boiler"] / c.boiler_life_yr
    if storage_kwh:
        invested["Heat storage"] = c.thermal_storage_capex(storage_kwh)
        investment["Heat storage"] = invested["Heat storage"] / c.thermal_storage_life_yr
    if battery_kwh:
        invested["Battery and EMS hardware"] = s.battery_investment(battery_kwh)
        investment["Battery and EMS hardware"] = invested["Battery and EMS hardware"] / c.battery_life_yr
    running_total, investment_total = sum(running.values()), sum(investment.values())
    return {"running": running, "investment": investment, "invested": invested, "running_total": running_total,
            "investment_total": investment_total, "total": running_total + investment_total, "other": other,
            "sizes": {k: v for k, v in sizes.items() if v}}


def table(cost: dict) -> pd.DataFrame:
    """One row per line of the yearly cost, for the results file."""
    rows = ([("Running", k, v) for k, v in cost["running"].items()] + [("Running", "Total running", cost["running_total"])]
            + [("Investment per year", k, v) for k, v in cost["investment"].items()]
            + [("Investment per year", "Total investment per year", cost["investment_total"]),
               ("Total", "Yearly cost of the site", cost["total"])]
            + [("Quantities", k, v) for k, v in cost["other"].items()])
    return pd.DataFrame(rows, columns=["Part", "Item", "Per year"])
