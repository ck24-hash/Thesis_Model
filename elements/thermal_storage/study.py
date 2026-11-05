"""The heat storage's year in the system, at the size the joint sizing chose (from_joint): heat stored and given back,
losses, heat released and gas with and without storage, per month, and the summary. The storage is valued against
the cheapest system without it (system/effects.py), line by line of the site's yearly cost, so a storage that shifts
the heat pump's electricity to cheaper hours is valued for its effect on the grid bill too. Without a gas boiler (the
heat pump as heat source) the gas columns and the gas the tank replaces are left out.
"""
from __future__ import annotations

import pandas as pd

from common.money import payback_years
from system.costs import co2_bought_cost, heat_running_cost
from system.setup import System

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def monthly(res: pd.DataFrame, base: pd.DataFrame, s: System) -> pd.DataFrame:
    dt, t = s.dt, s.storage
    gas = s.boiler is not None
    cost = s.gas.cost_per_kwh if gas else None
    var_om = s.commercial.boiler_var_om_per_kwh
    rows = []
    soc = res["storage_soc"]
    for m in range(1, 13):
        r, b = res[res.index.month == m], base[base.index.month == m]
        charged = r["storage_charge"].sum() * dt / 1000
        discharged = r["storage_discharge"].sum() * dt / 1000
        # heat in the tank at the end of the month before (the year is cyclic) and at the end of this one
        before = soc[soc.index < r.index[0]].iloc[-1] if m > 1 else soc.iloc[-1]
        change = (r["storage_soc"].iloc[-1] - before) / 1000

        def running(x):
            return (x["gas"] * cost.reindex(x.index) * dt).sum() + (x["boiler_heat"] * var_om * dt).sum()
        row = {
            "Heat stored (MWh)": charged,
            "Heat given back (MWh)": discharged,
            "Losses (MWh)": charged * t.eff_charge - discharged / t.eff_discharge - change,
            "Highest heat stored (MWh)": r["storage_soc"].max() / 1000,
            "Heat released, no storage (MWh)": b["heat_release"].sum() * dt / 1000,
            "Heat released, storage (MWh)": r["heat_release"].sum() * dt / 1000,
        }
        if gas:
            row.update({
                "Gas, no storage (MWh)": b["gas"].sum() * dt / 1000,
                "Gas, storage (MWh)": r["gas"].sum() * dt / 1000,
                "Gas the tank's heat replaces (MWh)": discharged / s.boiler.efficiency,
                "Extra gas to fill the tank (MWh)": discharged / s.boiler.efficiency
                                                     - (b["gas"].sum() - r["gas"].sum()) * dt / 1000,
                "Running cost saved": running(b) - running(r),
            })
        if s.heat_pump is not None:
            row.update({"Heat pump electricity, no storage (MWh)": b["hp_electricity"].sum() * dt / 1000,
                        "Heat pump electricity, storage (MWh)": r["hp_electricity"].sum() * dt / 1000})
        rows.append(row)
    return pd.DataFrame(rows, index=MONTHS)


def fuel_parts(res: pd.DataFrame, base: pd.DataFrame, s: System) -> dict:
    """Heat from the tank instead of burning gas: the gas its heat replaces (heat given back / boiler efficiency, at
    the gas price and levy of the moment it is given back), the extra gas burnt to fill it (gas replaced - gas saved),
    and the gas saved against the system without storage. Heat that would have been released anyway fills it for
    free. None without a gas boiler."""
    if s.boiler is None:
        return None
    dt, cost = s.dt, s.gas.cost_per_kwh
    replaced = res["storage_discharge"] / s.boiler.efficiency
    saved_mwh = (base["gas"].sum() - res["gas"].sum()) * dt / 1000
    saved_cost = float((base["gas"] * cost.reindex(base.index) * dt).sum() - (res["gas"] * cost.reindex(res.index) * dt).sum())
    replaced_mwh = float(replaced.sum() * dt / 1000)
    replaced_cost = float((replaced * cost.reindex(res.index) * dt).sum())
    return {"heat_given_back_mwh": float(res["storage_discharge"].sum() * dt / 1000),
            "gas_replaced_mwh": replaced_mwh, "gas_replaced_cost": replaced_cost,
            "extra_gas_mwh": replaced_mwh - saved_mwh, "extra_gas_cost": replaced_cost - saved_cost,
            "gas_saved_mwh": saved_mwh, "gas_saved_cost": saved_cost,
            "released_avoided_mwh": float((base["heat_release"].sum() - res["heat_release"].sum()) * dt / 1000)}


def value_parts(res: pd.DataFrame, base: pd.DataFrame, s: System, size: float, boiler_kw: float,
                boiler_kw_without: float, value: float | None = None) -> dict:
    """Where the storage's yearly value comes from, against the system without it (base): the gas, carbon levy and
    boiler variable O&M it saves, the smaller boiler's fixed O&M and investment per year (joint sizing only), minus its
    own fixed O&M. With `value`, what the parts do not explain (the rounding of the joint sizes) is a last part."""
    dt, c, g = s.dt, s.commercial, s.gas

    def gas(x):
        return float((x["gas"] * g.price.reindex(x.index) * dt).sum())

    def levy(x):
        return float((x["gas"] * g.levy_per_kwh * dt).sum())

    def var_om(x):
        return float((x["boiler_heat"] * c.boiler_var_om_per_kwh * dt).sum())
    parts = {"Heat storage O&M": -c.thermal_storage_fixed_om(size)}
    if s.boiler is not None:
        parts = {
            "Gas bought": gas(base) - gas(res),
            "Carbon levy": levy(base) - levy(res),
            "Boiler O&M, variable": var_om(base) - var_om(res),
            "Boiler O&M, fixed (smaller boiler)": c.boiler_fixed_om(boiler_kw_without) - c.boiler_fixed_om(boiler_kw),
            "Boiler investment per year (smaller boiler)":
                (c.boiler_capex(boiler_kw_without) - c.boiler_capex(boiler_kw)) / c.boiler_life_yr,
            **parts,
        }
    if s.external_co2 is not None:
        parts["CO2 bought"] = co2_bought_cost(base, s) - co2_bought_cost(res, s)
    if value is not None and abs(value - sum(parts.values())) >= 1:
        parts["Other (rounding of the joint sizes)"] = value - sum(parts.values())
    return parts


def effect_parts(effect: dict) -> dict:
    """Where the storage's yearly value comes from, from the system with and without it (system/effects.py): each
    line of the site's yearly cost it lowers (+) or raises (-), its own investment left out. They add up to its
    yearly value before its investment; lines under 0.5 are summed in "Other"."""
    parts, small = {}, 0.0
    for _, r in effect["costs"].iterrows():
        if r["Part"] == "Total" or str(r["Item"]).startswith("Total"):
            continue
        if r["Part"] == "Investment per year" and r["Item"] == "Heat storage":
            continue
        name = r["Item"] + (" (investment per year)" if r["Part"] == "Investment per year" else "")
        if abs(r["Effect"]) >= 0.5:
            parts[name] = -float(r["Effect"])
        else:
            small -= float(r["Effect"])
    if abs(small) >= 0.5:
        parts["Other"] = small
    return parts


def from_joint(s: System, res: pd.DataFrame, baseline: pd.DataFrame, system_value: float,
               boiler_kw_without: float | None, log=print, effect: dict | None = None) -> dict:
    """The heat storage's results when the joint sizing chose its size (s.storage_kwh): its year (res, the heat
    sources at their joint sizes) against the cheapest system without it (baseline: the rest re-sized without it).
    system_value is the site's yearly cost without it minus with it, after its own investment spread over its life;
    its yearly value (before that investment) gives the payback, as for the battery. effect: the with-and-without
    comparison (system/effects.py), for where the value comes from."""
    dt, c, t = s.dt, s.commercial, s.storage
    size, life = s.storage_kwh, c.thermal_storage_life_yr
    investment = c.thermal_storage_capex(size)
    value = system_value + investment / life
    charged = res["storage_charge"].sum() * dt / 1000
    discharged = res["storage_discharge"].sum() * dt / 1000
    row = dict(size=size, value=value, investment=investment, payback=payback_years(investment, value),
               lifetime_profit=system_value * life, heat_cost=heat_running_cost(res, s),
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
        "heat_running_cost_no_storage_yr": heat_running_cost(baseline, s), "heat_running_cost_storage_yr": row["heat_cost"],
        "storage_fixed_om_yr": c.thermal_storage_fixed_om(size),
        "boiler_kw_storage": s.boiler_kw, "boiler_kw_no_storage": boiler_kw_without,
        "gas_mwh_no_storage": baseline["gas"].sum() * dt / 1000, "gas_mwh_storage": row["gas_mwh"],
        "heat_released_mwh_no_storage": baseline["heat_release"].sum() * dt / 1000,
        "heat_released_mwh_storage": row["released_heat_mwh"],
        "heat_unmet_mwh_no_storage": baseline["heat_unmet"].sum() * dt / 1000,
        "heat_unmet_mwh_storage": row["unmet_heat_mwh"],
        "storage_charged_mwh": charged, "storage_discharged_mwh": discharged,
        "storage_losses_mwh": row["losses_mwh"], "storage_cycles": row["cycles"],
    }
    return {"summary": summary, "monthly": monthly(res, baseline, s),
            "dispatch": res, "baseline": baseline,
            "value_parts": (effect_parts(effect) if effect is not None
                            else value_parts(res, baseline, s, size, s.boiler_kw, boiler_kw_without or s.boiler_kw, value)),
            "fuel": fuel_parts(res, baseline, s),
            "choice": {"objective": "joint", "custom_kwh": None, "life_yr": life, "boiler_kw": s.boiler_kw,
                       "boiler_kw_without": boiler_kw_without, "heat_pump_kw": s.heat_pump_kw,
                       "heat_pump_kw_without": ((effect or {}).get("sizes_without") or {}).get("heat_pump"),
                       "system_value": system_value}}
