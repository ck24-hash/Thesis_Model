"""The dispatch: one PyPSA linear programme (HiGHS) that runs the system for a year with perfect foresight. Each
chosen block adds its own components on the site's electricity bus, in the battery model's order; the grid adds its
capacity charges and DUP lock. This file adds the rules that join two blocks (from elements/battery_reference
engine/dispatch.py):

PV on site (Voltiris + existing PV): both are behind the site's one meter and must run, so they are one generator
`pv` with their summed output, as in the reference model (zero output without either block).

EaaS bounds (Voltiris business model on the grid): exporting saves the EaaS fee on the Voltiris share, so the site
exports only its PV surplus and imports nothing during one. With a heat pump, the PV surplus goes to the heat pump
first, what is left is exported, and the site imports only what the heat pump draws beyond the surplus. With surplus
S (of the greenhouse load) and the heat pump's largest draw P at the step, time sharing within the quarter hour (as
for the one-meter rule) gives
    import <= max(1 - S/P, 0) x heat pump draw
so a heat pump that the surplus can run whole (P <= S) imports nothing.

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

Heat and CO2, when the system has a heat source (gas boiler, heat pump) or a CO2 source (gas boiler, external CO2):
a heat bus with the greenhouse's heat demand, a CO2 bus with its CO2 demand when it must be met, and a gas bus with
the boiler. The boiler is a link from gas to heat and CO2, the heat pump a link from the electricity bus to heat with
the COP of each step; at each step the optimisation takes heat from whichever is cheaper (the heat pump's electricity
at the step's import price, or PV, against the boiler's gas). Heat given beyond the demand is released
(heat_release) and CO2 beyond the demand is vented (co2_vent), both free. With a heat storage, heat may also go into
the tank and come back later. Without a heat or CO2 source the network is the electricity side only, as before.

The heat pump's electricity is part of the site's load: results() gives "load" = greenhouse load + heat pump, so the
bills, self-consumption and self-sufficiency count it. The PV-only battery account uses the greenhouse load as a
fixed number per step and does not see the heat pump (thesis.md A23: the PV the heat pump uses is not taken off the PV
the battery may store). Where exporting pays more than importing, the one-meter limit on the import is raised by the
heat pump's draw, so the heat pump may run on imported power while PV is exported there.
"""
from __future__ import annotations

import pandas as pd
import pypsa
import xarray as xr

from common.network import add_must_run
from elements.battery import block as battery
from elements.external_co2 import block as external_co2
from elements.gas_supply import block as gas_supply
from elements.greenhouse import block as greenhouse
from elements.grid import block as grid
from elements.heat_pump import block as heat_pump
from elements.ng_boiler import block as ng_boiler
from elements.thermal_storage import block as thermal_storage
from system.setup import System

PV = "pv"   # the site's PV generator (the reference model's name)


def load_estimate(s: System) -> pd.Series:
    """The site's load before solving: the greenhouse load, with a heat pump plus what it would draw to give the whole
    heat demand (for the automatic grid import limit)."""
    if s.heat_pump is None:
        return s.load
    return s.load + s.greenhouse.heat / s.heat_pump.cop


def site_load(n: pypsa.Network, s: System) -> pd.Series:
    """The site's electricity load in a solved network: the greenhouse load, plus the heat pump's draw."""
    if heat_pump.LINK in n.links.index:
        return s.load + n.links_t.p0[heat_pump.LINK]
    return s.load


def grid_limits_kw(s: System) -> tuple[float, float]:
    return s.grid.limits_kw(load_estimate(s), s.pv_total)


def choose_regime(s: System, auto: bool = True, manual: str | None = None) -> tuple[str, float | None]:
    """The regime without battery: from the DUP of what is drawn from the grid with all PV."""
    return s.grid.choose_regime((s.load - s.pv_total).clip(lower=0), auto, manual)


def _add_heat(n: pypsa.Network, s: System, boiler_kw: float | None, storage_kwh: float = 0.0,
              heat_slack: bool = True, co2_slack: bool = True, heat_pump_kw: float | None = None) -> None:
    """The heat, CO2 and gas side: with a CO2 source, the greenhouse's CO2 demand with its sources (the boiler's flue
    gas, bought CO2) and the free venting of surplus CO2; with a heat source, the heat demand, the gas supply and the
    boiler of boiler_kw kW of heat, the heat pump of heat_pump_kw kW of heat, the heat storage of storage_kwh (none at
    0) and the free release of surplus heat. The slacks keep the demand solvable where the sizes are fixed."""
    co2_max = 0.0
    if s.co2_blocks:
        n.add("Carrier", "co2")
        n.add("Bus", greenhouse.CO2_BUS, carrier="co2")
        s.greenhouse.add_co2_to(n, co2_slack)
    if s.heat_blocks:
        n.add("Carrier", "heat")
        if s.boiler is not None:
            n.add("Carrier", "gas")
        n.add("Bus", greenhouse.HEAT_BUS, carrier="heat")
        heat_kw = 0.0   # the most heat the units can give at once: the size of the free release
        if s.boiler is not None:
            s.gas.add_to(n, s.boiler.gas_kw(boiler_kw))
        s.greenhouse.add_heat_to(n, heat_slack)
        if s.boiler is not None:
            s.boiler.add_to(n, boiler_kw, s.gas.emission_factor, s.commercial.boiler_var_om_per_kwh)
            co2_max = s.boiler.gas_kw(boiler_kw) * s.gas.emission_factor * s.boiler.co2_use_frac
            heat_kw += boiler_kw
        if s.heat_pump is not None:
            s.heat_pump.add_to(n, heat_pump_kw)
            heat_kw += heat_pump_kw
        if s.storage is not None and storage_kwh:
            s.storage.add_to(n, storage_kwh)
            heat_kw += s.storage.power_kw(storage_kwh)
        if "efficiency2" in n.links.columns:
            n.links["efficiency2"] = n.links["efficiency2"].fillna(1.0)   # the links without a third bus (not the boiler)
        n.add("Generator", "heat_release", bus=greenhouse.HEAT_BUS, p_nom=max(heat_kw, 1.0),
              p_min_pu=-1, p_max_pu=0, marginal_cost=0)
    if s.external_co2 is not None:
        s.external_co2.add_to(n, float(s.greenhouse.co2.max()))
    if s.co2_blocks:
        n.add("Generator", "co2_vent", bus=greenhouse.CO2_BUS, p_nom=max(co2_max, 1.0), p_min_pu=-1, p_max_pu=0,
              marginal_cost=0)


def _add_components(n: pypsa.Network, s: System, regime: str, battery_kwh: float | None,
                    boiler_kw: float | None = None, storage_kwh: float = 0.0, heat_slack: bool = True,
                    co2_slack: bool | None = None, heat_pump_kw: float | None = None) -> None:
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
        # and export Voltiris power at once. With a heat pump, the import during a surplus is limited in _extra.
        surplus = (s.pv_total - s.load).clip(lower=0)
        n.generators_t.p_min_pu[grid.EXPORT] = -(surplus / p_exp).clip(upper=1.0)
        if s.heat_pump is None:
            n.generators_t.p_max_pu[grid.IMPORT] = (surplus <= 0).astype(float)
    if battery_kwh is not None:
        s.battery.add_to(n, battery_kwh)
        n.sanitize()
    if s.heat_side:
        _add_heat(n, s, boiler_kw, storage_kwh, heat_slack, heat_slack if co2_slack is None else co2_slack,
                  heat_pump_kw)


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
    if s.heat_pump is None:   # with a heat pump the import limit is a constraint with its draw (_extra)
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
        hp = m.variables["Link-p"].sel(name=heat_pump.LINK) if heat_pump.LINK in n.links.index else None
        if hp is not None and s.bm.eaas:
            # EaaS: during a PV surplus the heat pump runs on it first; import <= max(1 - S/P, 0) x its draw, P its
            # largest draw at the step (in the joint sizing, at the start size: the fixed size or the heat peak)
            surplus = (s.pv_total - s.load).clip(lower=0)
            on = surplus.index[(surplus > 0).values]
            if len(on):
                p_max = float(n.links.at[heat_pump.LINK, "p_nom"]) * n.links_t.p_max_pu[heat_pump.LINK].reindex(on)
                share = (1 - surplus.reindex(on) / p_max).clip(lower=0).where(p_max > 0, 0.0)
                index = pd.Index(on, name="snapshot")
                m.add_constraints(imp.sel(snapshot=on) - xr.DataArray(share.values, coords=[index]) * hp.sel(snapshot=on)
                                  <= 0, name="eaas_import_heat_pump")
        if hp is not None and len(both):
            # meter_bounds' import limit, raised by the heat pump's draw
            net = (s.load - s.pv_total).reindex(both)
            shortfall, surplus = net.clip(lower=0), (-net).clip(lower=0)
            c = float(n.links.at[battery.CHARGER, "p_nom"]) if with_battery else 0.0
            index = pd.Index(both, name="snapshot")
            limit = xr.DataArray((shortfall + (c - surplus).clip(lower=0)).values, coords=[index])
            m.add_constraints(imp.sel(snapshot=both) - hp.sel(snapshot=both) <= limit,
                              name="one_meter_import_heat_pump")
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
            lhs = imp.sel(snapshot=steps) - a * charge.sel(snapshot=steps)
            if hp is not None:   # the heat pump's draw is load too
                lhs = lhs - hp.sel(snapshot=steps)
            m.add_constraints(lhs <= xr.DataArray(shortfall.values, coords=[index]), name="one_meter_import")
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
          boiler_kw: float | None = None, storage_kwh: float | None = None,
          heat_pump_kw: float | None = None) -> pypsa.Network | None:
    """Solve the year without (battery_kwh None) or with a battery of that size, with the boiler at boiler_kw (else
    the size its study chose, s.boiler_kw), the heat pump at heat_pump_kw (else the joint sizing's, s.heat_pump_kw)
    and the heat storage at storage_kwh (else the size its study chose, s.storage_kwh; none before its study). None
    when the solver does not reach an optimum."""
    if battery_kwh is not None and s.battery is None:
        raise ValueError("A battery size was given, but the system has no battery block.")
    if s.boiler is not None:
        boiler_kw = boiler_kw if boiler_kw is not None else s.boiler_kw
        if boiler_kw is None:
            raise ValueError("The system has a gas boiler but no size for it: run its study first.")
    if s.heat_pump is not None:
        heat_pump_kw = heat_pump_kw if heat_pump_kw is not None else s.heat_pump_kw
        if heat_pump_kw is None:
            raise ValueError("The system has a heat pump but no size for it: run the joint sizing first.")
    if storage_kwh is None:
        storage_kwh = s.storage_kwh or 0.0
    n = pypsa.Network()
    _add_components(n, s, regime, battery_kwh, boiler_kw, storage_kwh, heat_pump_kw=heat_pump_kw)
    meter_bounds(n, s, regime, battery_kwh)
    status, _ = n.optimize(solver_name="highs", log_to_console=False, io_api="direct",
                           extra_functionality=_extra(s, regime, dup_lock, battery_kwh is not None))
    return n if status == "ok" else None


def pv_output(n: pypsa.Network, s: System) -> pd.Series:
    """All PV on site per step, kW: Voltiris and existing PV."""
    return n.generators_t.p[PV]


def results(n: pypsa.Network, s: System) -> pd.DataFrame:
    """The dispatch per step, kW: load, pv, grid_import, grid_export (positive), and battery_power (positive =
    discharge) and battery_soc when the network has a battery. With a heat pump, load is the greenhouse load + the
    heat pump's draw, also given apart as greenhouse_load and heat_pump."""
    out = {
        "load": site_load(n, s),
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
    if heat_pump.LINK in n.links.index:
        out["greenhouse_load"] = s.load
        out["heat_pump"] = n.links_t.p0[heat_pump.LINK]
    return pd.DataFrame(out, index=n.snapshots)


def heat_results(n: pypsa.Network, s: System) -> pd.DataFrame:
    """The heat and CO2 side per step: heat in kW, CO2 in kg/h, gas and the heat pump's electricity in kW (positive
    numbers); a column the system does not have is 0. With a heat storage also storage_charge, storage_discharge (kW)
    and storage_soc (kWh). At every step:
        heat  boiler_heat + hp_heat + heat_unmet + storage_discharge = heat_demand + heat_release + storage_charge
        CO2   co2_from_boiler + co2_bought + co2_unmet = co2_demand + co2_vented   (CO2 demand that must be met)"""
    gen, zero = n.generators_t.p, pd.Series(0.0, index=n.snapshots)
    link = ng_boiler.LINK
    boiler = link in n.links.index
    co2_demand = s.greenhouse.co2 if s.greenhouse.co2 is not None else zero
    from_boiler = -n.links_t.p2[link] if boiler else zero
    hp = heat_pump.HeatPump.results(n) if heat_pump.LINK in n.links.index else {"hp_heat": zero, "hp_electricity": zero}
    out = {
        "heat_demand": s.greenhouse.heat if s.greenhouse.heat is not None else zero,
        "boiler_heat": -n.links_t.p1[link] if boiler else zero,
        **hp,
        "heat_release": -gen.get("heat_release", zero),
        "heat_unmet": gen.get("heat_unmet", zero),
        "gas": n.links_t.p0[link] if boiler else zero,
        "co2_demand": co2_demand,
        "co2_from_boiler": from_boiler,
        "co2_bought": gen.get(external_co2.GENERATOR, zero),
        "co2_vented": -gen.get("co2_vent", zero),
    }
    if s.greenhouse.co2_mode == "required":
        out["co2_unmet"] = gen.get("co2_unmet", zero)
        out["co2_supplied"] = co2_demand - out["co2_unmet"]
    else:   # by-product: the greenhouse takes what the boiler gives, up to its demand
        out["co2_supplied"] = from_boiler.clip(upper=co2_demand)
        out["co2_unmet"] = co2_demand - out["co2_supplied"]
        out["co2_vented"] = from_boiler - out["co2_supplied"]
    out["co2_emitted"] = out["gas"] * s.gas.emission_factor if boiler else zero   # all the CO2 of the gas burnt
    if thermal_storage.CHARGER in n.links.index:
        out.update(thermal_storage.ThermalStorage.results(n))
    return pd.DataFrame(out, index=n.snapshots)

