"""The heat storage study: the storage block on its own, sized with the rest of the system fixed (the boiler at the
size its study chose, no battery while it runs). In the battery study's order:

1. the regime, and the year without storage (the boiler study's chosen year when it is given, else solved): its
   heat-side running cost is the baseline;
2. the size sweep (sizing.py) and the chosen size;
3. the chosen size's year: heat stored and given back, losses, heat released and gas with and without storage, per
   month, and the summary.

The chosen size is then fixed (s.storage_kwh) for the other studies.
"""
from __future__ import annotations

import gc

import pandas as pd

from common.money import payback_years
from elements.thermal_storage import sizing
from system import dispatch
from system.setup import System

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def monthly(res: pd.DataFrame, base: pd.DataFrame, s: System) -> pd.DataFrame:
    dt, t = s.dt, s.storage
    cost = s.gas.cost_per_kwh
    var_om = s.commercial.boiler_var_om_per_kwh
    rows = []
    for m in range(1, 13):
        r, b = res[res.index.month == m], base[base.index.month == m]
        charged = r["storage_charge"].sum() * dt / 1000
        discharged = r["storage_discharge"].sum() * dt / 1000

        def running(x):
            return (x["gas"] * cost.reindex(x.index) * dt).sum() + (x["boiler_heat"] * var_om * dt).sum()
        rows.append({
            "Heat stored (MWh)": charged,
            "Heat given back (MWh)": discharged,
            "Losses (MWh)": charged * t.eff_charge - discharged / t.eff_discharge,
            "Highest heat stored (MWh)": r["storage_soc"].max() / 1000,
            "Heat released, no storage (MWh)": b["heat_release"].sum() * dt / 1000,
            "Heat released, storage (MWh)": r["heat_release"].sum() * dt / 1000,
            "Gas, no storage (MWh)": b["gas"].sum() * dt / 1000,
            "Gas, storage (MWh)": r["gas"].sum() * dt / 1000,
            "Running cost saved": running(b) - running(r),
        })
    return pd.DataFrame(rows, index=MONTHS)


def run(s: System, *, regime_auto: bool = True, regime_manual: str | None = None,
        sizing_settings: dict | None = None, baseline: pd.DataFrame | None = None, log=print) -> dict:
    if s.storage is None:
        raise ValueError("The heat storage study needs a heat storage block in the system.")
    if s.boiler_kw is None:
        raise ValueError("The heat storage study needs the boiler's size: run the boiler study first.")
    cfg = {**sizing.DEFAULTS, **(sizing_settings or {})}
    dt, c, t = s.dt, s.commercial, s.storage

    # 1. regime and the year without storage
    base, _ = dispatch.choose_regime(s, regime_auto, regime_manual)
    log("\n=== HEAT STORAGE SIZING SWEEP ===")
    log(f"  Boiler fixed at {s.boiler_kw:,.0f} kW; heat loss: {t.loss_mode}, "
        f"{t.loss_per_hour.mean() * 100:.2f} % of the heat stored per hour on average")
    if baseline is None:
        log("  Solving the year without storage ...")
        n = dispatch.solve(s, base, storage_kwh=0)
        if n is None:
            raise RuntimeError("The year without storage could not be solved.")
        baseline = dispatch.heat_results(n, s)
        del n
    baseline_cost = sizing.heat_cost(baseline, s)

    # 2. sweep and choice
    solved: dict = {}
    table = sizing.sweep(s, base, baseline_cost, cfg, s.boiler_kw, log=log, dispatches=solved)
    life = c.thermal_storage_life_yr
    size = sizing.choose(table, cfg["objective"], cfg["custom_kwh"], life)
    row = table.loc[size]
    log(f"\n  Heat storage chosen: {size:,.0f} kWh")
    res = solved[size]
    solved.clear()
    gc.collect()
    s.storage_kwh = size

    # 3. the chosen size's year
    summary = {
        "currency": s.currency, "storage_objective": cfg["objective"], "storage_kwh": size,
        "storage_power_kw": t.power_kw(size), "storage_loss_mode": t.loss_mode,
        "storage_loss_per_hour_mean": float(t.loss_per_hour.mean()),
        "storage_value_yr": row["value"], "storage_investment": row["investment"],
        "storage_payback_yr": row["payback"], "storage_life_yr": life,
        "storage_lifetime_profit": row["lifetime_profit"],
        "heat_running_cost_no_storage_yr": baseline_cost, "heat_running_cost_storage_yr": row["heat_cost"],
        "storage_fixed_om_yr": c.thermal_storage_fixed_om(size),
        "gas_mwh_no_storage": baseline["gas"].sum() * dt / 1000, "gas_mwh_storage": row["gas_mwh"],
        "heat_released_mwh_no_storage": baseline["heat_release"].sum() * dt / 1000,
        "heat_released_mwh_storage": row["released_heat_mwh"],
        "heat_unmet_mwh_no_storage": baseline["heat_unmet"].sum() * dt / 1000,
        "heat_unmet_mwh_storage": row["unmet_heat_mwh"],
        "storage_charged_mwh": row["charged_mwh"], "storage_discharged_mwh": row["discharged_mwh"],
        "storage_losses_mwh": row["losses_mwh"], "storage_cycles": row["cycles"],
        "storage_sweep": table.reset_index()[["size", "value", "payback", "lifetime_profit"]].to_dict("records"),
    }
    return {"summary": summary, "sweep": table, "monthly": monthly(res, baseline, s), "dispatch": res,
            "baseline": baseline,
            "choice": {"objective": cfg["objective"], "custom_kwh": cfg["custom_kwh"], "life_yr": life,
                       "boiler_kw": s.boiler_kw}}


def from_joint(s: System, res: pd.DataFrame, baseline: pd.DataFrame, system_value: float,
               boiler_kw_without: float | None, log=print) -> dict:
    """The heat storage's results when the joint sizing chose its size (s.storage_kwh): its year (res, the boiler at
    its joint size) against the cheapest system without it (baseline: the boiler re-sized alone). system_value is the
    site's yearly cost without it minus with it, after its own investment spread over its life; its yearly value
    (before that investment) gives the payback, as for the battery."""
    dt, c, t = s.dt, s.commercial, s.storage
    size, life = s.storage_kwh, c.thermal_storage_life_yr
    investment = c.thermal_storage_capex(size)
    value = system_value + investment / life
    charged = res["storage_charge"].sum() * dt / 1000
    discharged = res["storage_discharge"].sum() * dt / 1000
    row = dict(size=size, value=value, investment=investment, payback=payback_years(investment, value),
               lifetime_profit=system_value * life, heat_cost=sizing.heat_cost(res, s),
               gas_mwh=res["gas"].sum() * dt / 1000, released_heat_mwh=res["heat_release"].sum() * dt / 1000,
               unmet_heat_mwh=res["heat_unmet"].sum() * dt / 1000, charged_mwh=charged, discharged_mwh=discharged,
               losses_mwh=charged * t.eff_charge - discharged / t.eff_discharge, cycles=discharged * 1000 / size)
    log(f"  Heat storage {size:,.0f} kWh (joint sizing): value {value:,.0f}/yr before its investment, "
        f"{system_value:,.0f}/yr after it")
    summary = {
        "currency": s.currency, "storage_objective": "joint", "storage_kwh": size,
        "storage_power_kw": t.power_kw(size), "storage_loss_mode": t.loss_mode,
        "storage_loss_per_hour_mean": float(t.loss_per_hour.mean()),
        "storage_value_yr": value, "storage_system_value_yr": system_value, "storage_investment": investment,
        "storage_payback_yr": row["payback"], "storage_life_yr": life, "storage_lifetime_profit": row["lifetime_profit"],
        "heat_running_cost_no_storage_yr": sizing.heat_cost(baseline, s), "heat_running_cost_storage_yr": row["heat_cost"],
        "storage_fixed_om_yr": c.thermal_storage_fixed_om(size),
        "boiler_kw_storage": s.boiler_kw, "boiler_kw_no_storage": boiler_kw_without,
        "gas_mwh_no_storage": baseline["gas"].sum() * dt / 1000, "gas_mwh_storage": row["gas_mwh"],
        "heat_released_mwh_no_storage": baseline["heat_release"].sum() * dt / 1000,
        "heat_released_mwh_storage": row["released_heat_mwh"],
        "heat_unmet_mwh_no_storage": baseline["heat_unmet"].sum() * dt / 1000,
        "heat_unmet_mwh_storage": row["unmet_heat_mwh"],
        "storage_charged_mwh": charged, "storage_discharged_mwh": discharged,
        "storage_losses_mwh": row["losses_mwh"], "storage_cycles": row["cycles"],
        "storage_sweep": [{k: row[k] for k in ("size", "value", "payback", "lifetime_profit")}],
    }
    return {"summary": summary, "sweep": pd.DataFrame([row]).set_index("size"), "monthly": monthly(res, baseline, s),
            "dispatch": res, "baseline": baseline,
            "choice": {"objective": "joint", "custom_kwh": None, "life_yr": life, "boiler_kw": s.boiler_kw,
                       "boiler_kw_without": boiler_kw_without, "system_value": system_value}}
