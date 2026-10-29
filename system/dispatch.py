"""The dispatch: one PyPSA linear programme (HiGHS) that runs the system for a year with perfect foresight. Each
chosen block adds its own components on the site's electricity bus, in the battery model's order; the grid adds its
capacity charges and DUP lock. This file adds the rules that join two blocks (from elements/battery_reference
engine/dispatch.py):

PV on site (Voltiris + existing PV): both are behind the site's one meter and must run, so they are one generator
`pv` with their summed output, as in the reference model (zero output without either block).

EaaS bounds (Voltiris business model on the grid): exporting saves the EaaS fee on the Voltiris share, so the site
exports only its PV surplus and imports nothing during one.

One meter (grid + battery), where the tariff makes cheating pay (export worth more than import, or a negative price):
a single meter imports or exports, and a battery charges or discharges, never both at the same moment. Within a
quarter hour they may switch (time sharing), so the exact limits on the step's averages are linear. With shortfall
D = (load - PV)+, surplus S = (PV - load)+, battery power P and discharge efficiency eta (constants per step):
    import <= D + max(1 - S/P, 0) x charging      export <= S + max(eta - D/P, 0) x discharging
    charging + discharging <= P
These use the net load as a fixed number per step: they hold while load and PV are fixed (PLAN.md section 5).

PV-only battery export (grid contract + battery, tariff key battery_export "pv_only"): the battery keeps an account of
its PV energy p; only PV energy may be exported, energy bought from the grid only serves the site:
    0 <= charging from PV <= PV surplus, charging from PV <= charging, discharging of PV energy <= discharging
    p(t) = (1 - loss)^dt x p(t-1) + dt x (eta_charge x charging from PV - discharging of PV energy),  0 <= p <= e
    export <= PV surplus - charging from PV + eta_discharge x discharging of PV energy
No tie-break term in the objective: a 1e-6 one made a French year about 50 times slower.

Heat and CO2 (greenhouse + gas supply + gas boiler), when the system has a heat block: a heat bus, a CO2 bus and a
gas bus. The greenhouse's heat demand (and its CO2 demand when it must be met) are loads; the boiler is a link from
gas to heat and CO2; heat the boiler gives beyond the demand is released (heat_release) and CO2 beyond the demand
is vented (co2_vent), both free. With a heat storage, heat may also go into the tank and come back later. Without a
heat block the network is the electricity side only, as before.
"""
from __future__ import annotations

import pandas as pd
import pypsa
import xarray as xr

from common.network import add_must_run
from elements.battery import block as battery
from elements.gas_supply import block as gas_supply
from elements.greenhouse import block as greenhouse
from elements.grid import block as grid
from elements.ng_boiler import block as ng_boiler
from elements.thermal_storage import block as thermal_storage
from system.setup import System

PV = "pv"   # the site's PV generator (the reference model's name)


def grid_limits_kw(s: System) -> tuple[float, float]:
    return s.grid.limits_kw(s.load, s.pv_total)


def choose_regime(s: System, auto: bool = True, manual: str | None = None) -> tuple[str, float | None]:
    """The regime without battery: from the DUP of what is drawn from the grid with all PV."""
    return s.grid.choose_regime((s.load - s.pv_total).clip(lower=0), auto, manual)


def _add_heat(n: pypsa.Network, s: System, boiler_kw: float, storage_kwh: float = 0.0, slack: bool = True) -> None:
    """The heat, CO2 and gas side: the greenhouse's demand, the gas supply, the boiler of boiler_kw kW of heat, the
    heat storage of storage_kwh (none at 0), and the free release of surplus heat and CO2."""
    for carrier in ("heat", "co2", "gas"):
        n.add("Carrier", carrier)
    n.add("Bus", greenhouse.HEAT_BUS, carrier="heat")
    n.add("Bus", greenhouse.CO2_BUS, carrier="co2")
    s.gas.add_to(n, s.boiler.gas_kw(boiler_kw))
    s.greenhouse.add_heat_co2_to(n, slack)
    s.boiler.add_to(n, boiler_kw, s.gas.emission_factor, s.commercial.boiler_var_om_per_kwh)
    storage_kw = 0.0
    if s.storage is not None and storage_kwh:
        s.storage.add_to(n, storage_kwh)
        storage_kw = s.storage.power_kw(storage_kwh)
    n.links["efficiency2"] = n.links["efficiency2"].fillna(1.0)   # the links without a third bus (not the boiler)
    n.add("Generator", "heat_release", bus=greenhouse.HEAT_BUS, p_nom=max(boiler_kw + storage_kw, 1.0), p_min_pu=-1,
          p_max_pu=0, marginal_cost=0)
    co2_max = s.boiler.gas_kw(boiler_kw) * s.gas.emission_factor * s.boiler.co2_use_frac
    n.add("Generator", "co2_vent", bus=greenhouse.CO2_BUS, p_nom=max(co2_max, 1.0), p_min_pu=-1, p_max_pu=0,
          marginal_cost=0)


def _add_components(n: pypsa.Network, s: System, regime: str, battery_kwh: float | None,
                    boiler_kw: float | None = None, storage_kwh: float = 0.0, heat_slack: bool = True) -> None:
    n.set_snapshots(s.index)
    n.snapshot_weightings.loc[:, :] = s.dt
    n.add("Carrier", "electricity")
    n.add("Bus", "main", carrier="electricity")
    add_must_run(n, PV, s.pv_total)
    s.greenhouse.add_to(n)
    p_imp, p_exp = grid_limits_kw(s)
    bm = s.bm
    s.grid.add_to(n, regime, p_imp, p_exp, export_static=bm.feed_in if bm.feed_in_is_fixed else 0,
                  export_value=bm.export_value if (bm.eaas or not bm.feed_in_is_fixed) else None)
    if bm.eaas:
        # One meter under EaaS: no import and export in the same step, otherwise the LP would buy cheap HD power
        # and export Voltiris power at once.
        surplus = (s.pv_total - s.load).clip(lower=0)
        n.generators_t.p_min_pu[grid.EXPORT] = -(surplus / p_exp).clip(upper=1.0)
        n.generators_t.p_max_pu[grid.IMPORT] = (surplus <= 0).astype(float)
    if battery_kwh is not None:
        s.battery.add_to(n, battery_kwh)
        n.sanitize()
    if s.boiler is not None:
        _add_heat(n, s, boiler_kw, storage_kwh, heat_slack)


def meter_bounds(n: pypsa.Network, s: System, regime: str, battery_kwh: float | None) -> pd.DatetimeIndex:
    """Where exporting is worth more than importing: the most a single meter can import and export in each step, set
    as bounds on the grid generators. With shortfall D and surplus S and a battery that charges at most c and
    delivers at most d to the bus, that is D + (c - S)+ and S + (d - D)+ (without a battery D and S: exact)."""
    both, _ = exclusive_steps(s, regime)
    if not len(both):
        return both
    net = (s.load - s.pv_total).reindex(both)
    shortfall, surplus = net.clip(lower=0), (-net).clip(lower=0)
    c = s.battery.tech.dispatch_kw(battery_kwh) if battery_kwh else 0.0
    d = c * s.battery.tech.eff_dispatch if battery_kwh else 0.0
    p_imp, p_exp = grid_limits_kw(s)
    imp_max = (shortfall + (c - surplus).clip(lower=0)).clip(upper=p_imp)
    exp_max = (surplus + (d - shortfall).clip(lower=0)).clip(upper=p_exp)
    p_max_imp = n.generators_t.p_max_pu.get(grid.IMPORT, pd.Series(1.0, index=s.index)).copy()
    p_min_exp = n.generators_t.p_min_pu.get(grid.EXPORT, pd.Series(-1.0, index=s.index)).copy()
    p_max_imp.loc[both] = (imp_max / p_imp).values
    p_min_exp.loc[both] = (-exp_max / p_exp).values
    n.generators_t.p_max_pu[grid.IMPORT] = p_max_imp
    n.generators_t.p_min_pu[grid.EXPORT] = p_min_exp
    return both


def exclusive_steps(s: System, regime: str) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Where the LP could cheat, so where the one-meter rules apply: (steps where exporting is worth more than
    importing, steps with a negative import or export price). Both empty for CH; NL has only negative-price steps."""
    if not s.one_meter:
        return pd.DatetimeIndex([]), pd.DatetimeIndex([])
    price = s.import_price(regime)
    value = s.bm.export_value
    both = pd.DatetimeIndex([]) if s.bm.eaas else price.index[(value > price).values]
    negative = price.index[((price < 0) | (value < 0)).values]
    return both, negative


def _extra(s: System, regime: str, dup_lock: str | None, with_battery: bool):
    """extra_functionality for n.optimize: the grid's capacity charges and DUP lock, then the one-meter rules."""

    def extra(n, snapshots):
        s.grid.add_constraints(n, snapshots, regime, dup_lock)
        m = n.model
        imp = m.variables["Generator-p"].sel(name=grid.IMPORT)
        both, negative = exclusive_steps(s, regime)
        steps = both.union(negative)
        if with_battery and len(steps):
            link = m.variables["Link-p"]
            charge, discharge = link.sel(name=battery.CHARGER), link.sel(name=battery.DISCHARGER)
            power = float(n.links.at[battery.CHARGER, "p_nom"])
            eta = float(n.links.at[battery.DISCHARGER, "efficiency"])
            m.add_constraints(charge.sel(snapshot=steps) + discharge.sel(snapshot=steps) <= power,
                              name="battery_charge_plus_discharge")
            net = (s.load - s.pv_total).reindex(steps)
            shortfall, surplus = net.clip(lower=0), (-net).clip(lower=0)
            index = pd.Index(steps, name="snapshot")
            a = xr.DataArray(((1 - surplus / power).clip(lower=0) if power > 0 else surplus * 0).values,
                             coords=[index])
            b = xr.DataArray(((eta - shortfall / power).clip(lower=0) if power > 0 else shortfall * 0).values,
                             coords=[index])
            exp = m.variables["Generator-p"].sel(name=grid.EXPORT)   # <= 0: export is -p
            m.add_constraints(imp.sel(snapshot=steps) - a * charge.sel(snapshot=steps)
                              <= xr.DataArray(shortfall.values, coords=[index]),
                              name="one_meter_import")
            if not s.bm.eaas:
                m.add_constraints(-exp.sel(snapshot=steps) - b * discharge.sel(snapshot=steps)
                                  <= xr.DataArray(surplus.values, coords=[index]),
                                  name="one_meter_export")
        if with_battery and s.battery_export == "pv_only":
            _pv_only_export(n, m, s)
    return extra


def _pv_only_export(n: pypsa.Network, m, s: System) -> None:
    """The battery exports only energy it stored from PV: a PV-energy account inside the battery. The surplus is a
    bound on the PV charging variable, so steps without surplus drop out in presolve."""
    index = pd.Index(n.snapshots, name="snapshot")
    surplus = xr.DataArray((s.pv_total - s.load).clip(lower=0).reindex(n.snapshots).values, coords=[index])
    link = m.variables["Link-p"]
    charge, discharge = link.sel(name=battery.CHARGER), link.sel(name=battery.DISCHARGER)
    e = m.variables["Store-e"].sel(name=battery.STORE)
    exp = m.variables["Generator-p"].sel(name=grid.EXPORT)   # <= 0: export is -p
    eta_c = float(n.links.at[battery.CHARGER, "efficiency"])
    eta_d = float(n.links.at[battery.DISCHARGER, "efficiency"])
    hours = float(n.snapshot_weightings.stores.iloc[0])
    keep = (1 - float(n.stores.at[battery.STORE, "standing_loss"])) ** hours
    charge_pv = m.add_variables(lower=0, upper=surplus, name="battery_charge_from_pv")
    discharge_pv = m.add_variables(lower=0, coords=[index], name="battery_discharge_of_pv_energy")
    pv_energy = m.add_variables(lower=0, coords=[index], name="battery_pv_energy")
    m.add_constraints(charge_pv - charge <= 0, name="pv_only_charge_from_pv_within_charge")
    m.add_constraints(discharge_pv - discharge <= 0, name="pv_only_pv_discharge_within_discharge")
    m.add_constraints(pv_energy - keep * pv_energy.roll(snapshot=1) - hours * eta_c * charge_pv
                      + hours * discharge_pv == 0, name="pv_only_pv_energy_balance")
    m.add_constraints(pv_energy - e <= 0, name="pv_only_pv_energy_within_battery")
    m.add_constraints(-exp + charge_pv - eta_d * discharge_pv <= surplus, name="pv_only_export_from_pv")


def solve(s: System, regime: str, battery_kwh: float | None = None, dup_lock: str | None = None,
          boiler_kw: float | None = None, storage_kwh: float | None = None) -> pypsa.Network | None:
    """Solve the year without (battery_kwh None) or with a battery of that size, with the boiler at boiler_kw (else
    the size its study chose, s.boiler_kw) and the heat storage at storage_kwh (else the size its study chose,
    s.storage_kwh; none before its study). None when the solver does not reach an optimum."""
    if battery_kwh is not None and s.battery is None:
        raise ValueError("A battery size was given, but the system has no battery block.")
    if s.boiler is not None:
        boiler_kw = boiler_kw if boiler_kw is not None else s.boiler_kw
        if boiler_kw is None:
            raise ValueError("The system has a gas boiler but no size for it: run its study first.")
    if storage_kwh is None:
        storage_kwh = s.storage_kwh or 0.0
    n = pypsa.Network()
    _add_components(n, s, regime, battery_kwh, boiler_kw, storage_kwh)
    meter_bounds(n, s, regime, battery_kwh)
    status, _ = n.optimize(solver_name="highs", log_to_console=False, io_api="direct",
                           extra_functionality=_extra(s, regime, dup_lock, battery_kwh is not None))
    return n if status == "ok" else None


def pv_output(n: pypsa.Network, s: System) -> pd.Series:
    """All PV on site per step, kW: Voltiris and existing PV."""
    return n.generators_t.p[PV]


def results(n: pypsa.Network, s: System) -> pd.DataFrame:
    """The dispatch per step, kW: load, pv, grid_import, grid_export (positive), and battery_power (positive =
    discharge) and battery_soc when the network has a battery."""
    out = {
        "load": s.load,
        "pv": pv_output(n, s),
        "grid_import": n.generators_t.p[grid.IMPORT],
        "grid_export": -n.generators_t.p[grid.EXPORT],
    }
    if battery.DISCHARGER in n.links.index:
        out.update(battery.Battery.results(n))
        if s.battery_export == "pv_only":
            # battery charging not covered by the step's PV surplus, i.e. bought from the grid
            surplus = (s.pv_total - s.load).clip(lower=0).reindex(n.snapshots)
            out["battery_charge_from_grid"] = (n.links_t.p0[battery.CHARGER] - surplus).clip(lower=0)
    return pd.DataFrame(out, index=n.snapshots)


def heat_results(n: pypsa.Network, s: System) -> pd.DataFrame:
    """The heat and CO2 side per step: heat in kW, CO2 in kg/h, gas in kW (positive numbers); with a heat storage
    also storage_charge, storage_discharge (kW) and storage_soc (kWh). Heat balance at every step:
        boiler_heat + heat_unmet + storage_discharge = heat_demand + heat_release + storage_charge"""
    link = ng_boiler.LINK
    gen = n.generators_t.p
    zero = pd.Series(0.0, index=n.snapshots)
    co2_demand = s.greenhouse.co2
    out = {
        "heat_demand": s.greenhouse.heat,
        "boiler_heat": -n.links_t.p1[link],
        "heat_release": -gen["heat_release"],
        "heat_unmet": gen.get("heat_unmet", zero),
        "gas": n.links_t.p0[link],
        "co2_demand": co2_demand,
        "co2_from_boiler": -n.links_t.p2[link],
        "co2_vented": -gen["co2_vent"],
    }
    if s.greenhouse.co2_mode == "required":
        out["co2_unmet"] = gen.get("co2_unmet", zero)
        out["co2_supplied"] = co2_demand - out["co2_unmet"]
    else:   # by-product: the greenhouse takes what the boiler gives, up to its demand
        out["co2_supplied"] = (-n.links_t.p2[link]).clip(upper=co2_demand)
        out["co2_unmet"] = co2_demand - out["co2_supplied"]
        out["co2_vented"] = -n.links_t.p2[link] - out["co2_supplied"]
    out["co2_emitted"] = n.links_t.p0[link] * s.gas.emission_factor   # all the CO2 of the gas burnt
    if thermal_storage.CHARGER in n.links.index:
        out.update(thermal_storage.ThermalStorage.results(n))
    return pd.DataFrame(out, index=n.snapshots)
