"""The gas boiler's year at its size (the joint sizing's, or fixed in the case), the rest of the system at its sizes
(no battery while it runs): heat, CO2 and gas per step, per month, and the summary.
"""
from __future__ import annotations

import pandas as pd

from elements.ng_boiler import sizing
from system import dispatch
from system.setup import System

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def monthly(res: pd.DataFrame, s: System) -> pd.DataFrame:
    dt, g = s.dt, s.gas
    rows = []
    for m in range(1, 13):
        r = res[res.index.month == m]
        rows.append({
            "Heat demand (MWh)": r["heat_demand"].sum() * dt / 1000,
            "Boiler heat (MWh)": r["boiler_heat"].sum() * dt / 1000,
            **({"Heat pump heat (MWh)": r["hp_heat"].sum() * dt / 1000} if s.heat_pump is not None else {}),
            "Heat released (MWh)": r["heat_release"].sum() * dt / 1000,
            "Heat unmet (MWh)": r["heat_unmet"].sum() * dt / 1000,
            "Gas (MWh)": r["gas"].sum() * dt / 1000,
            "Gas cost": (r["gas"] * g.price.reindex(r.index) * dt).sum(),
            "CO2 demand (t)": r["co2_demand"].sum() * dt / 1000,
            "CO2 supplied (t)": r["co2_supplied"].sum() * dt / 1000,
            "CO2 vented (t)": r["co2_vented"].sum() * dt / 1000,
            "CO2 emitted (t)": r["co2_emitted"].sum() * dt / 1000,
            "CO2 bought (t)": r["co2_bought"].sum() * dt / 1000,
        })
    return pd.DataFrame(rows, index=MONTHS)


def run(s: System, size: float, regime: str, log=print) -> dict:
    """The boiler's year at `size` kW of heat under `regime`; sets s.boiler_kw."""
    if s.boiler is None:
        raise ValueError("The boiler study needs a gas boiler block in the system.")
    dt, c, g = s.dt, s.commercial, s.gas
    need = sizing.needed_kw(s)
    log(f"  Gas boiler at {size:,.0f} kW (its busiest step alone would need {need:,.0f} kW):", end="")
    solved: dict = {}
    row = sizing.evaluate_size(s, size, regime, log=log, dispatches=solved)
    if row is None:
        raise RuntimeError(f"The year with a {size:,.0f} kW boiler could not be solved.")
    res = solved.pop(size)
    s.boiler_kw = size
    heat_demand = res["heat_demand"].sum() * dt / 1000
    co2_demand = res["co2_demand"].sum() * dt / 1000
    co2_supplied = res["co2_supplied"].sum() * dt / 1000
    summary = {
        "currency": s.currency, "boiler_objective": "joint",
        "boiler_kw": size, "boiler_needed_kw": need, "boiler_covers": bool(row["covers"]),
        "boiler_efficiency": s.boiler.efficiency, "co2_mode": s.greenhouse.co2_mode,
        "heat_demand_mwh": heat_demand, "boiler_heat_mwh": row["heat_mwh"],
        "heat_released_mwh": row["released_heat_mwh"], "heat_unmet_mwh": row["unmet_heat_mwh"],
        "gas_mwh": row["gas_mwh"], "gas_price_mean_per_kwh": float(g.price.mean()),
        "gas_cost_yr": row["gas_cost"], "co2_levy_yr": row["co2_levy"], "boiler_om_yr": row["om"],
        "co2_bought_t": row["co2_bought_t"], "co2_bought_cost_yr": row["co2_bought_cost"],
        "boiler_cost_yr": row["yearly_cost"], "boiler_investment": row["investment"],
        "boiler_life_yr": c.boiler_life_yr, "boiler_lifetime_cost": row["lifetime_cost"],
        # per MWh of heat met; with a heat pump, per MWh the boiler gives (the heat pump meets part of the demand)
        "heat_cost_per_mwh": ((row["investment"] / c.boiler_life_yr + row["yearly_cost"])
                              / max(row["heat_mwh"] if s.heat_pump is not None
                                    else heat_demand - row["unmet_heat_mwh"], 1e-9)),
        "hp_heat_mwh": res["hp_heat"].sum() * dt / 1000 if s.heat_pump is not None else None,
        "boiler_full_load_h": row["full_load_h"],
        "co2_demand_t": co2_demand, "co2_supplied_t": co2_supplied, "co2_unmet_t": row["unmet_co2_t"],
        "co2_vented_t": res["co2_vented"].sum() * dt / 1000, "co2_emitted_t": res["co2_emitted"].sum() * dt / 1000,
        "co2_self_sufficiency_pct": co2_supplied / co2_demand * 100 if co2_demand > 0 else None,
    }
    return {"summary": summary, "monthly": monthly(res, s), "dispatch": res,
            "choice": {"objective": "joint", "needed_kw": need, "life_yr": c.boiler_life_yr}}
