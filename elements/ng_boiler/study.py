"""The gas boiler study: the boiler block on its own, sized with the rest of the system fixed (no battery while it
runs; nothing links heat and electricity yet, so the battery would not change it). In the battery study's order:

1. the regime (the electricity side runs in every solve), and the heat the boiler must give at its busiest step;
2. the size sweep (sizing.py) and the chosen size;
3. the chosen size's year: heat, CO2 and gas per step, per month, and the summary.

The chosen size is then fixed (s.boiler_kw) for the other studies.
"""
from __future__ import annotations

import gc

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
            "Heat released (MWh)": r["heat_release"].sum() * dt / 1000,
            "Heat unmet (MWh)": r["heat_unmet"].sum() * dt / 1000,
            "Gas (MWh)": r["gas"].sum() * dt / 1000,
            "Gas cost": (r["gas"] * g.price.reindex(r.index) * dt).sum(),
            "CO2 demand (t)": r["co2_demand"].sum() * dt / 1000,
            "CO2 supplied (t)": r["co2_supplied"].sum() * dt / 1000,
            "CO2 vented (t)": r["co2_vented"].sum() * dt / 1000,
            "CO2 emitted (t)": r["co2_emitted"].sum() * dt / 1000,
        })
    return pd.DataFrame(rows, index=MONTHS)


def run(s: System, *, regime_auto: bool = True, regime_manual: str | None = None,
        sizing_settings: dict | None = None, log=print) -> dict:
    if s.boiler is None:
        raise ValueError("The boiler study needs a gas boiler block in the system.")
    cfg = {**sizing.DEFAULTS, **(sizing_settings or {})}
    dt, c, g = s.dt, s.commercial, s.gas

    # 1. regime and the size the demand needs
    base, _ = dispatch.choose_regime(s, regime_auto, regime_manual)
    need = sizing.needed_kw(s)
    log("\n=== BOILER SIZING SWEEP ===")
    log(f"  Heat the boiler must give at its busiest step: {need:,.0f} kW"
        + ("  (CO2 demand included)" if s.greenhouse.co2_mode == "required" else ""))

    # 2. sweep and choice
    solved: dict = {}
    table = sizing.sweep(s, base, cfg, log=log, dispatches=solved)
    size = sizing.choose(table, cfg["objective"], cfg["custom_kw"])
    row = table.loc[size]
    log(f"\n  Boiler chosen: {size:,.0f} kW" + ("" if row["covers"] else "  (no size tested covers the demand)"))
    res = solved[size]
    solved.clear()
    gc.collect()
    s.boiler_kw = size

    # 3. the chosen size's year
    heat_demand = res["heat_demand"].sum() * dt / 1000
    co2_demand = res["co2_demand"].sum() * dt / 1000
    co2_supplied = res["co2_supplied"].sum() * dt / 1000
    summary = {
        "currency": s.currency, "boiler_objective": cfg["objective"],
        "boiler_kw": size, "boiler_needed_kw": need, "boiler_covers": bool(row["covers"]),
        "boiler_efficiency": s.boiler.efficiency, "co2_mode": s.greenhouse.co2_mode,
        "heat_demand_mwh": heat_demand, "boiler_heat_mwh": row["heat_mwh"],
        "heat_released_mwh": row["released_heat_mwh"], "heat_unmet_mwh": row["unmet_heat_mwh"],
        "gas_mwh": row["gas_mwh"], "gas_price_mean_per_kwh": float(g.price.mean()),
        "gas_cost_yr": row["gas_cost"], "co2_levy_yr": row["co2_levy"], "boiler_om_yr": row["om"],
        "boiler_cost_yr": row["yearly_cost"], "boiler_investment": row["investment"],
        "boiler_life_yr": c.boiler_life_yr, "boiler_lifetime_cost": row["lifetime_cost"],
        "heat_cost_per_mwh": ((row["investment"] / c.boiler_life_yr + row["yearly_cost"])
                              / max(heat_demand - row["unmet_heat_mwh"], 1e-9)),
        "boiler_full_load_h": row["full_load_h"],
        "co2_demand_t": co2_demand, "co2_supplied_t": co2_supplied, "co2_unmet_t": row["unmet_co2_t"],
        "co2_vented_t": res["co2_vented"].sum() * dt / 1000, "co2_emitted_t": res["co2_emitted"].sum() * dt / 1000,
        "co2_self_sufficiency_pct": co2_supplied / co2_demand * 100 if co2_demand > 0 else None,
        "boiler_sweep": table.reset_index()[["size", "covers", "yearly_cost", "lifetime_cost"]].to_dict("records"),
    }
    return {"summary": summary, "sweep": table, "monthly": monthly(res, s), "dispatch": res,
            "choice": {"objective": cfg["objective"], "custom_kw": cfg["custom_kw"], "needed_kw": need,
                       "life_yr": c.boiler_life_yr}}
