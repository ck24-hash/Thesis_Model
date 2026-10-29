"""Gas boiler sizing, with the battery's logic (elements/battery/sizing.py): every size in a list is optimised over the
whole year, then one is chosen by an objective.

For a size: the year's heat and CO2 with that boiler, what stays unmet, the gas burnt, the yearly cost (gas, carbon
levy, fixed and variable O&M), the investment, and the lifetime cost = investment + yearly cost x boiler life. A size
covers the demand when it leaves (almost) nothing unmet. Objectives:
    lifetime_cost   the lowest lifetime cost among the sizes that cover the demand (default)
    smallest        the smallest size that covers the demand
    custom          the tested size closest to custom_kw
When no size covers the demand, the largest one tested is kept and the summary says it does not cover.
"""
from __future__ import annotations

import gc
import math

import pandas as pd

from system import dispatch
from system.setup import System

DEFAULTS = {
    "objective": "lifetime_cost",
    "custom_kw": None,
    "sizes_kw": [],          # empty: around the size the demand needs, needed_kw x AUTO_STEPS
}
AUTO_STEPS = (0.8, 0.9, 1.0, 1.1, 1.25, 1.5)
COVER_TOL = 1e-6   # share of the year's demand that may stay unmet for a size to count as covering it


def needed_kw(s: System) -> float:
    """The heat the boiler must give at its busiest step: the heat demand, or, when the CO2 demand must be met, the
    heat that comes with the gas burnt for it, whichever is larger."""
    heat = s.greenhouse.heat
    co2_per_heat = s.gas.emission_factor * s.boiler.co2_use_frac / s.boiler.efficiency   # kg CO2 per kWh of heat
    if s.greenhouse.co2_mode == "required" and co2_per_heat > 0:
        heat = pd.concat([heat, s.greenhouse.co2 / co2_per_heat], axis=1).max(axis=1)
    return float(heat.max())


def size_list(s: System, cfg: dict) -> list[float]:
    """The sizes to solve, kW of heat: the case's list, or the needed size x AUTO_STEPS rounded up to 10 kW."""
    sizes = list(cfg["sizes_kw"] or [])
    if not sizes:
        need = needed_kw(s)
        sizes = [math.ceil(need * f / 10) * 10 for f in AUTO_STEPS]
    if cfg["objective"] == "custom" and cfg["custom_kw"]:
        sizes.append(cfg["custom_kw"])
    return sorted({float(x) for x in sizes if x > 0})


def evaluate_size(s: System, size_kw: float, regime: str, log=print, dispatches: dict | None = None) -> dict | None:
    """Solve the year with a boiler of size_kw (no battery) and value it. With `dispatches`, its heat table is kept
    there under the size."""
    log(f"  {size_kw:>8,.0f} kW ...", end="")
    n = dispatch.solve(s, regime, boiler_kw=size_kw)
    if n is None:
        log(" FAILED")
        return None
    res = dispatch.heat_results(n, s)
    del n
    gc.collect()
    dt, c, g = s.dt, s.commercial, s.gas
    heat_demand_mwh = res["heat_demand"].sum() * dt / 1000
    co2_demand_t = res["co2_demand"].sum() * dt / 1000
    unmet_heat_mwh = res["heat_unmet"].sum() * dt / 1000
    unmet_co2_t = res["co2_unmet"].sum() * dt / 1000
    heat_mwh = res["boiler_heat"].sum() * dt / 1000
    gas_cost = (res["gas"] * g.price * dt).sum()
    levy = (res["gas"] * g.levy_per_kwh * dt).sum()
    om = c.boiler_fixed_om(size_kw) + heat_mwh * 1000 * c.boiler_var_om_per_kwh
    yearly = gas_cost + levy + om
    investment = c.boiler_capex(size_kw)
    covers = (unmet_heat_mwh <= COVER_TOL * max(heat_demand_mwh, 1e-9)
              and (s.greenhouse.co2_mode != "required" or unmet_co2_t <= COVER_TOL * max(co2_demand_t, 1e-9)))
    if dispatches is not None:
        dispatches[size_kw] = res
    log(f" heat {heat_mwh:,.0f} MWh  unmet heat {unmet_heat_mwh:,.1f} MWh  unmet CO2 {unmet_co2_t:,.1f} t  "
        f"cost {yearly:,.0f}/yr  lifetime {investment + yearly * c.boiler_life_yr:,.0f}"
        + ("" if covers else "  (does not cover the demand)"))
    return dict(size=size_kw, covers=covers, heat_mwh=heat_mwh, released_heat_mwh=res["heat_release"].sum() * dt / 1000,
                unmet_heat_mwh=unmet_heat_mwh, unmet_co2_t=unmet_co2_t, gas_mwh=res["gas"].sum() * dt / 1000,
                gas_cost=gas_cost, co2_levy=levy, om=om, yearly_cost=yearly, investment=investment,
                lifetime_cost=investment + yearly * c.boiler_life_yr,
                full_load_h=heat_mwh * 1000 / size_kw)


def choose(table: pd.DataFrame, objective: str, custom_kw: float | None) -> float:
    if objective == "custom" and custom_kw:
        return float(min(table.index, key=lambda size: abs(size - custom_kw)))
    covering = table[table["covers"]]
    if covering.empty:
        return float(table.index.max())
    if objective == "smallest":
        return float(covering.index.min())
    return float(covering["lifetime_cost"].idxmin())


def sweep(s: System, regime: str, cfg: dict, log=print, dispatches: dict | None = None) -> pd.DataFrame:
    sizes = size_list(s, cfg)
    log(f"Boiler sizes: {[round(x) for x in sizes]} kW")
    rows = [r for r in (evaluate_size(s, size, regime, log=log, dispatches=dispatches) for size in sizes) if r is not None]
    if not rows:
        raise RuntimeError("No boiler size could be solved.")
    return pd.DataFrame(rows).set_index("size")
