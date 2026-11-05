"""The site's yearly cost: what the grower pays in a year for the run's system at its sizes, in one table (thesis.md
section 8, money flows). Two parts:

    running     the grid bill (energy and network, capacity charges, minus the export revenue, the EaaS fee; the heat
                pump's electricity is in it), gas, carbon levy, O&M of the boiler, the heat pump and the heat
                storage, the CO2 bought, the battery's EMS costs minus its ancillary revenue
    investment  each investment spread over its life (investment / life, no discounting: the same rule as the
                studies' lifetime profit and lifetime cost): Voltiris modules (direct sales; under EaaS the grower
                pays the fee instead), boiler, heat pump, heat storage, battery with its EMS hardware

The battery is spread over the PV life, as the battery study's payback table counts it: its first purchase after the
subsidy with the EMS hardware, and its replacements within the PV life at a share of the gross price, unsubsidised
(battery_per_year). Existing PV is sunk. Heat or CO2 demand left unmet is reported, not priced.
"""
from __future__ import annotations

import pandas as pd

from system import flows
from system.setup import System


def co2_bought_cost(res: pd.DataFrame, s: System) -> float:
    """What the CO2 bought costs over the year (0 without an external CO2 supply)."""
    if s.external_co2 is None:
        return 0.0
    return float((res["co2_bought"] * s.external_co2.price.reindex(res.index) * s.dt).sum())


def battery_per_year(s: System, size_kwh: float, ems_hardware: bool = True) -> float:
    """The battery's investment per year over the PV life: the first purchase after its subsidy (with the EMS hardware
    unless ems_hardware is False) and the replacements within the PV life (a share of the gross price, unsubsidised),
    over the PV life."""
    first = s.battery_investment(size_kwh) if ems_hardware else s.battery_net_capex(size_kwh)
    replacements = max(s.commercial.battery_replacement_cost(size_kwh, s.pv_life_yr), 0.0)
    return (first + replacements) / s.pv_life_yr


def heat_running_cost(heat: pd.DataFrame, s: System) -> float:
    """The heat side's running cost over the year for a dispatch: gas with its carbon levy, the boiler's variable O&M
    and the CO2 bought. The heat pump's electricity is not in it: it is in the grid bill."""
    dt, cost = s.dt, 0.0
    if s.gas is not None:
        cost += float((heat["gas"] * s.gas.cost_per_kwh.reindex(heat.index) * dt).sum()
                      + (heat["boiler_heat"] * s.commercial.boiler_var_om_per_kwh * dt).sum())
    return cost + co2_bought_cost(heat, s)


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
    (dispatch.heat_results) when the system has a heat side; sizes: {"ng_boiler": kW, "heat_pump": kW,
    "thermal_storage": kWh, "battery": kWh}; the battery's EMS costs: ems_yr, or from the bill without battery (its
    fees are a share of the saving)."""
    sizes = sizes or {}
    dt, c = s.dt, s.commercial
    boiler_kw, hp_kw, storage_kwh, battery_kwh = (sizes.get(k) or 0.0
                                                  for k in ("ng_boiler", "heat_pump", "thermal_storage", "battery"))
    running = {
        "Grid: energy and network": grid["import_cost"],
        "Grid: capacity charges": grid["capacity_charges"],
        "Grid: export revenue": -grid["export_revenue"],
    }
    if grid.get("eaas_fee"):
        running["Voltiris EaaS fee"] = grid["eaas_fee"]
    other = {"Grid import (MWh)": grid["import_mwh"], "Grid export (MWh)": grid["export_mwh"]}
    if heat is not None and s.gas is not None:
        running["Gas"] = float((heat["gas"] * s.gas.price.reindex(heat.index) * dt).sum())
        running["Carbon levy"] = float((heat["gas"] * s.gas.levy_per_kwh * dt).sum())
        running["Boiler O&M"] = (c.boiler_fixed_om(boiler_kw)
                                 + float((heat["boiler_heat"] * c.boiler_var_om_per_kwh * dt).sum()))
    if heat is not None and s.heat_pump is not None and hp_kw:
        running["Heat pump O&M"] = c.heat_pump_fixed_om(hp_kw)
    if heat is not None:
        if storage_kwh:
            running["Heat storage O&M"] = c.thermal_storage_fixed_om(storage_kwh)
        if s.external_co2 is not None:
            running["CO2 bought"] = co2_bought_cost(heat, s)
            if s.external_co2.fixed_per_year:
                running["CO2 supply: fixed"] = s.external_co2.fixed_per_year
            other["CO2 bought (t)"] = float(heat["co2_bought"].sum() * dt / 1000)
        if s.heat_pump is not None:
            other.update({"Heat pump heat (MWh)": float(heat["hp_heat"].sum() * dt / 1000),
                          "Heat pump electricity (MWh)": float(heat["hp_electricity"].sum() * dt / 1000)})
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
    if hp_kw:
        invested["Heat pump"] = c.heat_pump_capex(hp_kw)
        investment["Heat pump"] = invested["Heat pump"] / c.heat_pump_life_yr
    if storage_kwh:
        invested["Heat storage"] = c.thermal_storage_capex(storage_kwh)
        investment["Heat storage"] = invested["Heat storage"] / c.thermal_storage_life_yr
    if battery_kwh:
        invested["Battery and EMS hardware"] = s.battery_investment(battery_kwh)
        investment["Battery and EMS hardware"] = battery_per_year(s, battery_kwh)
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
