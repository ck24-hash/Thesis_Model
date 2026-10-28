"""The dispatch: a PyPSA linear programme (HiGHS) that runs the site for a year with perfect foresight.

One bus with the load, the PV (must run, not curtailable), grid import at the tariff's price and export at the export
value, and optionally a battery (store + charge and discharge links). The capacity charges are part of the objective:
a monthly peak (with or without the annual ratchet), a yearly peak, or the TURPE staircase. A DUP lock can keep the
year's DUP inside one regime (see sizing).

One meter, where the tariff makes cheating pay (export worth more than import, as for most of a French year against a
fixed contract price; or a negative price, as at times in NL): a single meter imports or exports, and a battery charges
or discharges, never both at the same moment. Within a quarter hour they may switch (time sharing), so the exact limits
on the step's averages are linear. With shortfall D = (load - PV)+, surplus S = (PV - load)+, battery power P and
discharge efficiency eta (constants per step):
    import <= D + max(1 - S/P, 0) x charging      export <= S + max(eta - D/P, 0) x discharging
    charging + discharging <= P
(charging covers the surplus before anything is imported, and discharging covers the shortfall before anything is
exported). CH never meets either case, so it is unchanged. Under EaaS the import/export rule is the CH model's fixed
bounds instead (export only the PV surplus, no import during one); the battery rule still applies at negative prices.

Battery export rule (the supply contract's, tariff key battery_export): "any" (CH, NL) lets the battery export whatever
it holds; "pv_only" (FR: a fixed-price contract may not be resold) lets it export only energy it stored from PV. The
battery then keeps an account of its PV energy p (the rest, e - p, is energy bought from the grid), sharing the
battery's capacity and power and following the store's own balance (standing loss, cyclic year):
    0 <= charging from PV <= PV surplus, charging from PV <= charging, discharging of PV energy <= discharging
    p(t) = (1 - loss)^dt x p(t-1) + dt x (eta_charge x charging from PV - discharging of PV energy),  0 <= p <= e
    export <= PV surplus - charging from PV + eta_discharge x discharging of PV energy
Grid energy can still serve the load (peak shaving) but never leaves the meter. Where it makes no difference, the LP
may book PV charging either way, so the results report grid charging as the charging the step's PV surplus does not
cover (no tie-break in the objective: a 1e-6 one made a French year 50 times slower). Off ("any") adds nothing, so CH
is unchanged.
"""
from __future__ import annotations

import pandas as pd
import pypsa
import xarray as xr

from engine.setup import Setup


def grid_limits_kw(s: Setup) -> tuple[float, float]:
    st = s.study
    p_nom_import = s.grid_import_max_kw if s.grid_import_max_kw is not None else float(st.load.max()) * 2.0
    p_nom_export = s.grid_export_max_kw if s.grid_export_max_kw is not None else float(st.pv_total.max()) * 1.1
    return p_nom_import, p_nom_export


def _add_common_components(n: pypsa.Network, s: Setup, regime: str) -> None:
    st = s.study
    n.set_snapshots(st.index)
    n.snapshot_weightings.loc[:, :] = s.dt
    n.add("Carrier", "electricity")
    n.add("Bus", "main", carrier="electricity")

    p_nom_pv = float(st.pv_total.max())
    pv_pu = (st.pv_total / p_nom_pv).clip(upper=1.0) if p_nom_pv > 0 else st.pv_total * 0.0
    n.add("Generator", "pv", bus="main", p_nom=p_nom_pv, marginal_cost=0)
    n.generators_t.p_max_pu["pv"] = pv_pu
    n.generators_t.p_min_pu["pv"] = pv_pu

    n.add("Load", "load", bus="main", p_set=st.load)
    p_nom_import, p_nom_export = grid_limits_kw(s)
    n.add("Generator", "grid_import", bus="main", p_nom=p_nom_import, p_min_pu=0, marginal_cost=0)
    n.generators_t.marginal_cost["grid_import"] = s.import_price(regime)
    fixed = s.bm.feed_in if s.bm.feed_in_is_fixed else 0
    n.add("Generator", "grid_export", bus="main", p_nom=p_nom_export, p_min_pu=-1, p_max_pu=0, marginal_cost=fixed)
    if s.bm.eaas or not s.bm.feed_in_is_fixed:
        n.generators_t.marginal_cost["grid_export"] = s.bm.export_value
    if s.bm.eaas:
        # Exporting saves the EaaS fee on the Voltiris share (export_value). One meter: no import and export in the
        # same step, otherwise the LP would buy cheap HD power and export Voltiris power at once.
        surplus = (st.pv_total - st.load).clip(lower=0)
        n.generators_t.p_min_pu["grid_export"] = -(surplus / p_nom_export).clip(upper=1.0)
        n.generators_t.p_max_pu["grid_import"] = (surplus <= 0).astype(float)


def _add_battery(n: pypsa.Network, s: Setup, battery_kwh: float) -> None:
    """The battery the LP may dispatch: battery_kwh is the bought size; the ancillary reserve (energy and power)
    is left out."""
    b = s.battery
    n.add("Bus", "battery_bus", carrier="electricity")
    n.add("Store", "battery_store", bus="battery_bus", e_nom=b.dispatch_kwh(battery_kwh), e_cyclic=True,
          standing_loss=b.self_discharge_per_hour, marginal_cost=0)
    n.add("Link", "bat_charger", bus0="main", bus1="battery_bus", p_nom=b.dispatch_kw(battery_kwh),
          efficiency=b.eff_store, marginal_cost=0)
    n.add("Link", "bat_discharger", bus0="battery_bus", bus1="main", p_nom=b.dispatch_kw(battery_kwh),
          efficiency=b.eff_dispatch, marginal_cost=0)


def meter_bounds(n: pypsa.Network, s: Setup, regime: str, battery_kwh: float | None) -> pd.DatetimeIndex:
    """Where exporting is worth more than importing: the most a single meter can import and export in each step, set
    as bounds on the grid generators. PV and load are fixed, so with shortfall D = (load - PV)+ and surplus
    S = (PV - load)+ and a battery that charges at most c and delivers at most d to the bus, that is D + (c - S)+ and
    S + (d - D)+ (without a battery D and S: exact). Returns those steps."""
    both, _ = exclusive_steps(s, regime)
    if not len(both):
        return both
    st = s.study
    net = (st.load - st.pv_total).reindex(both)
    shortfall, surplus = net.clip(lower=0), (-net).clip(lower=0)
    c = s.battery.dispatch_kw(battery_kwh) if battery_kwh else 0.0
    d = c * s.battery.eff_dispatch
    p_imp, p_exp = grid_limits_kw(s)
    imp_max = (shortfall + (c - surplus).clip(lower=0)).clip(upper=p_imp)
    exp_max = (surplus + (d - shortfall).clip(lower=0)).clip(upper=p_exp)
    p_max_imp = n.generators_t.p_max_pu.get("grid_import", pd.Series(1.0, index=st.index)).copy()
    p_min_exp = n.generators_t.p_min_pu.get("grid_export", pd.Series(-1.0, index=st.index)).copy()
    p_max_imp.loc[both] = (imp_max / p_imp).values
    p_min_exp.loc[both] = (-exp_max / p_exp).values
    n.generators_t.p_max_pu["grid_import"] = p_max_imp
    n.generators_t.p_min_pu["grid_export"] = p_min_exp
    return both


def exclusive_steps(s: Setup, regime: str) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Where the LP could cheat, so where the one-meter rules apply: (steps where exporting is worth more than
    importing, steps with a negative import or export price). Both empty for CH; NL has only negative-price steps."""
    if not s.one_meter:
        return pd.DatetimeIndex([]), pd.DatetimeIndex([])
    price = s.import_price(regime)
    value = s.bm.export_value
    both = pd.DatetimeIndex([]) if s.bm.eaas else price.index[(value > price).values]
    negative = price.index[((price < 0) | (value < 0)).values]
    return both, negative


def _extra(s: Setup, regime: str, dup_lock: str | None, battery: bool):
    """extra_functionality for n.optimize: the capacity charges in the objective, the DUP lock, and the one-meter
    rules."""
    tariff, dt = s.tariff, s.dt

    def extra(n, snapshots):
        m = n.model
        imp = m.variables["Generator-p"].sel(name="grid_import")
        main = tariff.main_monthly_charge
        main_last = None
        for name, c in tariff.charges:
            if c["type"] == "monthly_peak":
                mask = tariff.window_mask(c["window"], pd.DatetimeIndex(snapshots))
                window_sns = [ts for ts, on in zip(snapshots, mask.values) if on]
                if not window_sns:
                    continue
                rate = tariff.charge_rate(c, regime)
                ratchet = c.get("ratchet") == "annual"
                prev = None
                for month in range(1, 13):
                    month_sns = [ts for ts in window_sns if ts.month == month]
                    if not month_sns and (prev is None or not ratchet):
                        continue
                    p_peak = m.add_variables(lower=0, name=f"{name}_peak_m{month:02d}")
                    if month_sns:
                        m.add_constraints(p_peak - imp.sel(snapshot=month_sns) >= 0, name=f"{name}_m{month:02d}")
                    if ratchet and prev is not None:
                        m.add_constraints(p_peak - prev >= 0, name=f"{name}_ratchet_m{month:02d}")
                    m.objective = m.objective + rate * p_peak
                    prev = p_peak
                if c is main:
                    main_last = prev
            elif c["type"] == "yearly_peak":
                mask = tariff.window_mask(c["window"], pd.DatetimeIndex(snapshots))
                sns = [ts for ts, on in zip(snapshots, mask.values) if on]
                if not sns:
                    continue
                p_peak = m.add_variables(lower=0, name=f"{name}_peak_year")
                m.add_constraints(p_peak - imp.sel(snapshot=sns) >= 0, name=f"{name}_year")
                m.objective = m.objective + tariff.charge_rate(c, regime) * p_peak
            elif c["type"] == "staircase":
                slots = tariff.slots(pd.DatetimeIndex(snapshots))
                rates = tariff.staircase_rates(c, regime)
                prev = None
                for i, (slot, b) in enumerate(rates):
                    sns = list(slots.index[(slots == slot).values])
                    p_s = m.add_variables(lower=0, name=f"{name}_{slot}")
                    if sns:
                        m.add_constraints(p_s - imp.sel(snapshot=sns) >= 0, name=f"{name}_{slot}_bound")
                    if prev is not None:
                        m.add_constraints(p_s - prev >= 0, name=f"{name}_{slot}_stair")
                    increment = b - rates[i + 1][1] if i < len(rates) - 1 else b
                    m.objective = m.objective + increment * p_s
                    prev = p_s
            else:
                raise ValueError(f"unknown capacity charge type {c['type']!r}")
        # DUP lock (see sizing): DUP = yearly import / December's billed peak kept at or below (A) or above (B) the
        # threshold. Under lock A the LP may bill a peak above the metered one; in practice the controller just lets
        # one HP interval reach it, at negligible energy cost.
        if dup_lock is not None and main_last is not None and tariff.dup_threshold_h is not None:
            annual_imp = (imp * dt).sum()
            thr = tariff.dup_threshold_h
            if dup_lock == tariff.rule["at_or_below"]:
                m.add_constraints(thr * main_last - annual_imp >= 0, name=f"dup_lock_{dup_lock}")
            else:
                m.add_constraints(annual_imp - thr * main_last >= 0, name=f"dup_lock_{dup_lock}")
        # One meter where cheating could pay (the static bounds come from meter_bounds).
        both, negative = exclusive_steps(s, regime)
        steps = both.union(negative)
        if battery and len(steps):
            link = m.variables["Link-p"]
            charge, discharge = link.sel(name="bat_charger"), link.sel(name="bat_discharger")
            power = float(n.links.at["bat_charger", "p_nom"])
            eta = float(n.links.at["bat_discharger", "efficiency"])
            m.add_constraints(charge.sel(snapshot=steps) + discharge.sel(snapshot=steps) <= power,
                              name="battery_charge_plus_discharge")
            st = s.study
            net = (st.load - st.pv_total).reindex(steps)
            shortfall, surplus = net.clip(lower=0), (-net).clip(lower=0)
            index = pd.Index(steps, name="snapshot")
            a = xr.DataArray(((1 - surplus / power).clip(lower=0) if power > 0 else surplus * 0).values,
                             coords=[index])
            b = xr.DataArray(((eta - shortfall / power).clip(lower=0) if power > 0 else shortfall * 0).values,
                             coords=[index])
            exp = m.variables["Generator-p"].sel(name="grid_export")   # <= 0: export is -p
            m.add_constraints(imp.sel(snapshot=steps) - a * charge.sel(snapshot=steps)
                              <= xr.DataArray(shortfall.values, coords=[index]),
                              name="one_meter_import")
            if not s.bm.eaas:
                m.add_constraints(-exp.sel(snapshot=steps) - b * discharge.sel(snapshot=steps)
                                  <= xr.DataArray(surplus.values, coords=[index]),
                                  name="one_meter_export")
        if battery and s.battery_export == "pv_only":
            _pv_only_export(n, m, s, imp)
    return extra


def _pv_only_export(n: pypsa.Network, m, s: Setup, imp) -> None:
    """The battery exports only energy it stored from PV: a PV-energy account inside the battery (see the module
    docstring). The surplus is a bound on the PV charging variable, so steps without surplus drop out in presolve."""
    st = s.study
    index = pd.Index(n.snapshots, name="snapshot")
    surplus = xr.DataArray((st.pv_total - st.load).clip(lower=0).reindex(n.snapshots).values, coords=[index])
    link = m.variables["Link-p"]
    charge, discharge = link.sel(name="bat_charger"), link.sel(name="bat_discharger")
    e = m.variables["Store-e"].sel(name="battery_store")
    exp = m.variables["Generator-p"].sel(name="grid_export")   # <= 0: export is -p
    eta_c = float(n.links.at["bat_charger", "efficiency"])
    eta_d = float(n.links.at["bat_discharger", "efficiency"])
    hours = float(n.snapshot_weightings.stores.iloc[0])
    keep = (1 - float(n.stores.at["battery_store", "standing_loss"])) ** hours
    charge_pv = m.add_variables(lower=0, upper=surplus, name="battery_charge_from_pv")
    discharge_pv = m.add_variables(lower=0, coords=[index], name="battery_discharge_of_pv_energy")
    pv_energy = m.add_variables(lower=0, coords=[index], name="battery_pv_energy")
    m.add_constraints(charge_pv - charge <= 0, name="pv_only_charge_from_pv_within_charge")
    m.add_constraints(discharge_pv - discharge <= 0, name="pv_only_pv_discharge_within_discharge")
    m.add_constraints(pv_energy - keep * pv_energy.roll(snapshot=1) - hours * eta_c * charge_pv
                      + hours * discharge_pv == 0, name="pv_only_pv_energy_balance")
    m.add_constraints(pv_energy - e <= 0, name="pv_only_pv_energy_within_battery")
    m.add_constraints(-exp + charge_pv - eta_d * discharge_pv <= surplus, name="pv_only_export_from_pv")


def solve(s: Setup, regime: str, battery_kwh: float | None = None, dup_lock: str | None = None) -> pypsa.Network | None:
    """Solve the year without (battery_kwh None) or with a battery. None when the solver does not reach an optimum."""
    n = pypsa.Network()
    _add_common_components(n, s, regime)
    if battery_kwh is not None:
        _add_battery(n, s, battery_kwh)
        n.sanitize()
    meter_bounds(n, s, regime, battery_kwh)
    status, _ = n.optimize(solver_name="highs", log_to_console=False, io_api="direct",
                           extra_functionality=_extra(s, regime, dup_lock, battery_kwh is not None))
    return n if status == "ok" else None


def results(n: pypsa.Network, s: Setup) -> pd.DataFrame:
    """The dispatch per step, kW: load, pv, grid_import, grid_export (positive), and battery_power (positive =
    discharge) and battery_soc when the network has a battery."""
    out = {
        "load": s.study.load,
        "pv": n.generators_t.p["pv"],
        "grid_import": n.generators_t.p["grid_import"],
        "grid_export": -n.generators_t.p["grid_export"],
    }
    if "bat_discharger" in n.links.index:
        out["battery_power"] = -n.links_t.p1["bat_discharger"] - n.links_t.p0["bat_charger"]
        out["battery_soc"] = n.stores_t.e["battery_store"]
        if s.battery_export == "pv_only":
            # battery charging not covered by the step's PV surplus, i.e. bought from the grid
            surplus = (s.study.pv_total - s.study.load).clip(lower=0).reindex(n.snapshots)
            out["battery_charge_from_grid"] = (n.links_t.p0["bat_charger"] - surplus).clip(lower=0)
    return pd.DataFrame(out, index=n.snapshots)
