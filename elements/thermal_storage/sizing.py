"""Heat storage sizing, with the battery's logic (elements/battery/sizing.py): every size in a list is optimised over
the whole year with the boiler at its chosen size, and valued against the year without storage.

For a size: its yearly value is the heat-side running cost it saves (gas, carbon levy, the boiler's variable O&M)
minus its own fixed O&M; its investment; payback = investment / value; lifetime profit = value x storage life -
investment. Objectives, as the battery's:
    profit    the highest lifetime profit among the sizes that pay back within the storage life; if none does, the
              shortest payback (default)
    payback   the shortest payback
    custom    the tested size closest to custom_kwh, which is added to the list
"""
from __future__ import annotations

import gc
import math

import pandas as pd

from common.money import payback_years
from system import dispatch
from system.setup import System

DEFAULTS = {
    "objective": "profit",
    "custom_kwh": None,
    "sizes_kwh": [],          # empty: the boiler's size x AUTO_HOURS
}
AUTO_HOURS = (1, 2, 4, 8, 12)   # automatic sizes: hours of the boiler at full output, rounded up to 100 kWh


def heat_cost(res: pd.DataFrame, s: System) -> float:
    """The heat side's running cost over the year for a dispatch: gas with its carbon levy, and the boiler's variable
    O&M. Fixed costs (investments, fixed O&M) are not in it."""
    dt = s.dt
    return float((res["gas"] * s.gas.cost_per_kwh * dt).sum()
                 + (res["boiler_heat"] * s.commercial.boiler_var_om_per_kwh * dt).sum())


def size_list(s: System, cfg: dict, boiler_kw: float) -> list[float]:
    """The sizes to solve, kWh of heat: the case's list, or the boiler's size x AUTO_HOURS."""
    sizes = list(cfg["sizes_kwh"] or [])
    if not sizes:
        sizes = [math.ceil(boiler_kw * h / 100) * 100 for h in AUTO_HOURS]
    if cfg["objective"] == "custom" and cfg["custom_kwh"]:
        sizes.append(cfg["custom_kwh"])
    return sorted({float(x) for x in sizes if x > 0})


def evaluate_size(s: System, size_kwh: float, regime: str, baseline_cost: float, log=print,
                  dispatches: dict | None = None) -> dict | None:
    """Solve the year with a storage of size_kwh (the boiler at its chosen size) and value it against the year
    without storage. With `dispatches`, its heat table is kept there under the size."""
    log(f"  {size_kwh:>8,.0f} kWh of heat ...", end="")
    n = dispatch.solve(s, regime, storage_kwh=size_kwh)
    if n is None:
        log(" FAILED")
        return None
    res = dispatch.heat_results(n, s)
    del n
    gc.collect()
    dt, c, t = s.dt, s.commercial, s.storage
    cost = heat_cost(res, s)
    value = baseline_cost - cost - c.thermal_storage_fixed_om(size_kwh)
    investment = c.thermal_storage_capex(size_kwh)
    charged = res["storage_charge"].sum() * dt / 1000
    discharged = res["storage_discharge"].sum() * dt / 1000
    if dispatches is not None:
        dispatches[size_kwh] = res
    payback = payback_years(investment, value)
    log(f" value {value:,.0f}/yr  payback {payback:,.1f} yr  stored {charged:,.0f} MWh  "
        f"released {res['heat_release'].sum() * dt / 1000:,.0f} MWh")
    return dict(size=size_kwh, value=value, investment=investment, payback=payback,
                lifetime_profit=value * c.thermal_storage_life_yr - investment, heat_cost=cost,
                gas_mwh=res["gas"].sum() * dt / 1000, released_heat_mwh=res["heat_release"].sum() * dt / 1000,
                unmet_heat_mwh=res["heat_unmet"].sum() * dt / 1000, charged_mwh=charged, discharged_mwh=discharged,
                losses_mwh=charged * t.eff_charge - discharged / t.eff_discharge,
                cycles=discharged * 1000 / size_kwh)


def choose(table: pd.DataFrame, objective: str, custom_kwh: float | None, life_yr: float) -> float:
    if objective == "custom" and custom_kwh:
        return float(min(table.index, key=lambda size: abs(size - custom_kwh)))
    if objective == "profit":
        valid = table[table["payback"] <= life_yr]
        return float(valid["lifetime_profit"].idxmax()) if not valid.empty else float(table["payback"].idxmin())
    return float(table["payback"].idxmin())


def sweep(s: System, regime: str, baseline_cost: float, cfg: dict, boiler_kw: float, log=print,
          dispatches: dict | None = None) -> pd.DataFrame:
    sizes = size_list(s, cfg, boiler_kw)
    log(f"Heat storage sizes: {[round(x) for x in sizes]} kWh")
    rows = [r for r in (evaluate_size(s, size, regime, baseline_cost, log=log, dispatches=dispatches)
                        for size in sizes) if r is not None]
    if not rows:
        raise RuntimeError("No heat storage size could be solved.")
    return pd.DataFrame(rows).set_index("size")
