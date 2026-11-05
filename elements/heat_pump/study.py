"""The heat pump's results. It is sized in the joint sizing (system/joint.py) or fixed at a given size, so it has no
size sweep of its own. From the site's heat side at the sizes chosen (the year solved with every block):

1. its size, its COP over the year (constant or from the outside temperature) and its seasonal performance factor
   (SPF: heat given / electricity drawn over the year);
2. the heat it gives against the demand and the other heat sources, and the electricity it draws, per month;
3. its electricity at the import price of each step (the energy and network price per kWh; capacity charges and the
   PV it uses are in the grid bill, not here), its investment and O&M, and its cost per MWh of heat, next to the gas
   boiler's running cost per MWh of heat.

What it brings to the site, against the system without it, is in system/effects.py."""
from __future__ import annotations

import math

import pandas as pd

from system.setup import System

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def monthly(heat: pd.DataFrame, s: System, price: pd.Series) -> pd.DataFrame:
    dt, hp = s.dt, s.heat_pump
    rows = []
    for m in range(1, 13):
        r = heat[heat.index.month == m]
        el = r["hp_electricity"].sum() * dt / 1000
        row = {
            "Heat demand (MWh)": r["heat_demand"].sum() * dt / 1000,
            "Heat pump heat (MWh)": r["hp_heat"].sum() * dt / 1000,
        }
        if s.boiler is not None:
            row["Boiler heat (MWh)"] = r["boiler_heat"].sum() * dt / 1000
        if "storage_discharge" in r.columns:
            row["From the tank (MWh)"] = r["storage_discharge"].sum() * dt / 1000
        row.update({
            "Heat released (MWh)": r["heat_release"].sum() * dt / 1000,
            "Heat unmet (MWh)": r["heat_unmet"].sum() * dt / 1000,
            "Heat pump electricity (MWh)": el,
            "Mean COP": float(hp.cop.reindex(r.index).mean()),
            "COP of the heat given": row["Heat pump heat (MWh)"] / el if el > 0 else None,
        })
        if hp.outside_temp is not None:
            row["Mean outside temperature (°C)"] = float(hp.outside_temp.reindex(r.index).mean())
        row["Electricity cost"] = float((r["hp_electricity"] * price.reindex(r.index) * dt).sum())
        rows.append(row)
    return pd.DataFrame(rows, index=MONTHS)


def cop_curve(s: System) -> list[list[float]]:
    """The COP at each whole degree of outside temperature over the year's range (flat when constant)."""
    hp = s.heat_pump
    if hp.outside_temp is None:
        return []
    lo, hi = math.floor(hp.outside_temp.min()), math.ceil(hp.outside_temp.max())
    out = []
    for t in range(lo, hi + 1):
        cop = (hp.cop_nominal if hp.cop_mode == "constant"
               else hp.cop_nominal * (hp.supply_temp_c - hp.ref_outside_temp_c) / (hp.supply_temp_c - t))
        out.append([t, cop])
    return out


def run(s: System, heat: pd.DataFrame, regime: str, fixed: bool = False, log=print) -> dict:
    """The heat pump at its size (s.heat_pump_kw) in the site's year (heat: dispatch.heat_results of that year),
    its electricity priced at the regime's import price. fixed: its size was given, not sized."""
    if s.heat_pump is None:
        raise ValueError("The heat pump's results need a heat pump block in the system.")
    hp, dt, c = s.heat_pump, s.dt, s.commercial
    size = s.heat_pump_kw or 0.0
    price = s.import_price(regime).reindex(heat.index)
    heat_mwh = float(heat["hp_heat"].sum() * dt / 1000)
    el_mwh = float(heat["hp_electricity"].sum() * dt / 1000)
    demand_mwh = float(heat["heat_demand"].sum() * dt / 1000)
    el_cost = float((heat["hp_electricity"] * price * dt).sum())
    investment = c.heat_pump_capex(size)
    fixed_om = c.heat_pump_fixed_om(size)
    life = c.heat_pump_life_yr
    summary = {
        "currency": s.currency, "heat_pump_kw": size, "sized": "fixed" if fixed else "joint",
        "cop_mode": hp.cop_mode, "cop_nominal": hp.cop_nominal, "supply_temp_c": hp.supply_temp_c,
        "ref_outside_temp_c": hp.ref_outside_temp_c,
        "cop_mean": float(hp.cop.mean()), "cop_min": hp.cop_min, "cop_max": float(hp.cop.max()),
        "spf": heat_mwh / el_mwh if el_mwh > 0 else None,
        "heat_demand_mwh": demand_mwh, "hp_heat_mwh": heat_mwh,
        "hp_heat_share_pct": heat_mwh / demand_mwh * 100 if demand_mwh > 0 else None,
        "boiler_heat_mwh": float(heat["boiler_heat"].sum() * dt / 1000),
        "heat_unmet_mwh": float(heat["heat_unmet"].sum() * dt / 1000),
        "hp_electricity_mwh": el_mwh, "hp_electricity_peak_kw": float(heat["hp_electricity"].max()),
        "hp_electricity_max_kw": hp.electricity_kw(size),
        "hp_electricity_cost_yr": el_cost, "hp_electricity_price_paid": el_cost / (el_mwh * 1000) if el_mwh > 0 else None,
        "hp_full_load_h": heat_mwh * 1000 / size if size else None,
        "hp_investment": investment, "hp_life_yr": life, "hp_fixed_om_yr": fixed_om,
        "hp_investment_per_year": investment / life,
        "hp_heat_cost_per_mwh": ((el_cost + fixed_om + investment / life) / heat_mwh) if heat_mwh > 0 else None,
        "hp_running_cost_per_mwh": el_cost / heat_mwh if heat_mwh > 0 else None,
        "regime": regime,
    }
    if s.boiler is not None:   # what a MWh of heat from the boiler costs to run, on average over the year
        summary["boiler_running_cost_per_mwh"] = float(
            (s.gas.cost_per_kwh.mean() / s.boiler.efficiency + s.commercial.boiler_var_om_per_kwh) * 1000)
    if hp.outside_temp is not None:
        summary.update(outside_temp_mean=float(hp.outside_temp.mean()), outside_temp_min=float(hp.outside_temp.min()),
                       outside_temp_max=float(hp.outside_temp.max()))
    log(f"\n=== HEAT PUMP ===\n  {size:,.0f} kW of heat ({'fixed' if fixed else 'sized together'}): "
        f"{heat_mwh:,.0f} MWh of heat from {el_mwh:,.0f} MWh of electricity"
        + (f" (SPF {summary['spf']:.2f})" if summary["spf"] else "") + f", COP {hp.cop_min:.2f} to {summary['cop_max']:.2f}")
    return {"summary": summary, "monthly": monthly(heat, s, price), "dispatch": heat, "cop": hp.cop,
            "cop_curve": cop_curve(s)}
