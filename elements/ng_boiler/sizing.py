"""The gas boiler at a size: the size its busiest step needs, and the year solved with a boiler of that size (heat and
CO2 per step, what stays unmet, the gas burnt, the yearly cost: gas, carbon levy, fixed and variable O&M, the CO2
bought; the investment, and the lifetime cost = investment + yearly cost x boiler life). A size covers the demand when
it leaves (almost) nothing unmet. The size itself comes from the joint sizing (system/joint.py) or the case.
"""
from __future__ import annotations

import gc

import pandas as pd

from system import dispatch
from system.costs import co2_bought_cost
from system.setup import System

COVER_TOL = 1e-6   # share of the year's demand that may stay unmet for a size to count as covering it


def needed_kw(s: System) -> float:
    """The heat the boiler must give at its busiest step: the heat demand, or, when the CO2 demand must be met, the
    heat that comes with the gas burnt for it, whichever is larger."""
    heat = s.greenhouse.heat
    co2_per_heat = s.gas.emission_factor * s.boiler.co2_use_frac / s.boiler.efficiency   # kg CO2 per kWh of heat
    if s.greenhouse.co2_mode == "required" and s.external_co2 is None and co2_per_heat > 0:
        heat = pd.concat([heat, s.greenhouse.co2 / co2_per_heat], axis=1).max(axis=1)
    return float(heat.max())


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
    co2_bought = co2_bought_cost(res, s)
    yearly = gas_cost + levy + om + co2_bought
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
                gas_cost=gas_cost, co2_levy=levy, om=om, co2_bought_cost=co2_bought,
                co2_bought_t=res["co2_bought"].sum() * dt / 1000, yearly_cost=yearly, investment=investment,
                lifetime_cost=investment + yearly * c.boiler_life_yr,
                full_load_h=heat_mwh * 1000 / size_kw)

