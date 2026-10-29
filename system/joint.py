"""Joint sizing: the sizes of every sized block chosen together in one optimisation (PyPSA capacity expansion), for the
lowest yearly cost of the whole site: running costs (grid, gas, carbon levy, variable O&M) + each investment spread
over its life + fixed O&M - the battery's ancillary revenue. It is the rule of each block's own study (lifetime
profit, lifetime cost) applied to all of them at once, so a block that lets another be smaller is valued for it (a
heat storage that lets the boiler be smaller).

The sized blocks: the gas boiler (kW of heat), the heat storage (kWh of heat), the battery (kWh bought). A block whose
sizing objective is "custom" keeps that size. When the boiler's size is free, the heat and CO2 demand must be met
(no slack).

Exact in the optimisation: the boiler and the heat storage (linear prices and O&M). Approximated, then checked:
- the battery's price per kWh (tiers, subsidy), usable share and reserve are taken at a reference size (the largest
  allowed), and the optimisation is repeated once at the size found when they differ there;
- the battery's EMS costs (fixed, fees on the saving) are not in it: the battery is kept only if it still lowers the
  site's yearly cost with them;
- the battery is at most the subsidised maximum (cap_at_subsidy_size, CH) or the largest size of its list;
- the one-meter rules use the reference size's battery power (they apply only where exporting pays more than
  importing, or prices are negative; never in CH);
- the regime (CH): solved under the starting regime; when the result's DUP crosses the threshold, solved again with
  the DUP held in each regime, and the cheaper kept (as the battery study does).

Then each sized block is left out once and the others re-sized: the site's yearly cost without it minus with it is
its value in the system. The boiler is not left out while it is the only heat source.
"""
from __future__ import annotations

import gc
import math

import pypsa

from elements.battery import block as battery
from elements.battery import sizing as battery_sizing
from elements.gas_supply import block as gas_supply
from elements.ng_boiler import block as ng_boiler
from elements.thermal_storage import block as thermal_storage
from system import costs, dispatch
from system.setup import System

SIZED = ("ng_boiler", "thermal_storage", "battery")
NAMES = {"ng_boiler": "gas boiler", "thermal_storage": "heat storage", "battery": "battery"}
UNITS = {"ng_boiler": "kW", "thermal_storage": "kWh", "battery": "kWh"}


def plan_of(s: System, blocks: dict) -> dict:
    """The sized blocks of the system: block -> its fixed size (objective "custom") or None (sized here)."""
    present = {"ng_boiler": s.boiler, "thermal_storage": s.storage, "battery": s.battery}
    key = {"ng_boiler": "custom_kw", "thermal_storage": "custom_kwh", "battery": "custom_kwh"}
    plan = {}
    for b in SIZED:
        if present[b] is None:
            continue
        cfg = (blocks.get(b) or {}).get("sizing") or {}
        plan[b] = float(cfg[key[b]]) if cfg.get("objective") == "custom" and cfg.get(key[b]) else None
    return plan


def battery_limit(s: System, blocks: dict) -> float:
    """The largest battery the joint sizing may choose: the subsidised maximum (with cap_at_subsidy_size and a
    threshold subsidy), else the largest size of the battery's list."""
    cfg = {**battery_sizing.DEFAULTS, **((blocks.get("battery") or {}).get("sizing") or {})}
    if cfg["cap_at_subsidy_size"] and s.subsidies.cap_sweep_at_subsidy:
        return float(round(s.subsidies.battery_threshold_kwh))
    return float(max(cfg["sweep_kwh"]))


def battery_terms(s: System, size: float) -> dict:
    """The battery's linear terms at a reference size: usable kWh and kW per kWh bought, the yearly cost per kWh
    bought (net price / battery life) and the ancillary revenue per kWh bought."""
    t, c = s.battery.tech, s.commercial
    return {"k_e": t.dispatch_kwh(size) / size, "k_p": t.dispatch_kw(size) / size,
            "cost": s.battery_net_capex(size) / size / c.battery_life_yr,
            "ancillary": s.ancillary_revenue(size) / size}


def _extendable(table, name: str, attr: str, cost: float, upper: float = math.inf) -> None:
    table.loc[name, f"{attr}_extendable"] = True
    table.loc[name, "capital_cost"] = cost
    table.loc[name, f"{attr}_min"] = 0.0
    table.loc[name, f"{attr}_max"] = upper


def _network(s: System, regime: str, plan: dict, b_ref: float, b_max: float, dup_lock: str | None):
    """The network with the free sizes as variables; solved. Returns (network or None, battery terms or None)."""
    c = s.commercial
    free = {b for b, v in plan.items() if v is None}
    boiler_kw = None
    if s.boiler is not None:
        boiler_kw = plan.get("ng_boiler") or float(s.greenhouse.heat.max())   # a start value when it is free
    storage_kwh = 0.0 if "thermal_storage" not in plan else (plan["thermal_storage"] or 1.0)
    battery_kwh = None if "battery" not in plan else (plan["battery"] or b_ref)
    n = pypsa.Network()
    dispatch._add_components(n, s, regime, battery_kwh, boiler_kw, storage_kwh, heat_slack="ng_boiler" not in free)
    dispatch.meter_bounds(n, s, regime, battery_kwh)
    terms = None
    if free & {"ng_boiler", "thermal_storage"}:   # what follows the heat blocks' sizes is free of cost
        _extendable(n.generators, "heat_release", "p_nom", 0.0)
    if "ng_boiler" in free:
        per_kw_th = c.capex["boiler_per_kw_th"] / c.boiler_life_yr + c.capex["boiler_fixed_om_per_kw_year"]
        _extendable(n.links, ng_boiler.LINK, "p_nom", per_kw_th * s.boiler.efficiency)   # p_nom is kW of gas
        _extendable(n.generators, gas_supply.GENERATOR, "p_nom", 0.0)
        _extendable(n.generators, "co2_vent", "p_nom", 0.0)
    if "thermal_storage" in free:
        _extendable(n.stores, thermal_storage.STORE, "e_nom",
                    c.capex["thermal_storage_per_kwh"] / c.thermal_storage_life_yr
                    + c.capex["thermal_storage_fixed_om_per_kwh_year"])
        _extendable(n.links, thermal_storage.CHARGER, "p_nom", 0.0)
        _extendable(n.links, thermal_storage.DISCHARGER, "p_nom", 0.0)
    if "battery" in free:
        terms = battery_terms(s, b_ref)
        _extendable(n.stores, battery.STORE, "e_nom", (terms["cost"] - terms["ancillary"]) / terms["k_e"],
                    upper=terms["k_e"] * b_max)
        _extendable(n.links, battery.CHARGER, "p_nom", 0.0)
        _extendable(n.links, battery.DISCHARGER, "p_nom", 0.0)
    base_extra = dispatch._extra(s, regime, dup_lock, battery_kwh is not None)

    def extra(n, snapshots):
        base_extra(n, snapshots)
        m = n.model
        p_nom = m.variables["Link-p_nom"] if "Link-p_nom" in m.variables else None
        if "thermal_storage" in free:   # the tank's power follows its size
            e = m.variables["Store-e_nom"].sel(name=thermal_storage.STORE)
            pp = s.storage.power_per_kwh
            m.add_constraints(p_nom.sel(name=thermal_storage.CHARGER) - pp * e == 0, name="heat_store_charger_size")
            m.add_constraints(p_nom.sel(name=thermal_storage.DISCHARGER) - pp / s.storage.eff_discharge * e == 0,
                              name="heat_store_discharger_size")
        if "battery" in free:            # the battery's power follows its size
            e = m.variables["Store-e_nom"].sel(name=battery.STORE)
            ratio = terms["k_p"] / terms["k_e"]
            m.add_constraints(p_nom.sel(name=battery.CHARGER) - ratio * e == 0, name="battery_charger_size")
            m.add_constraints(p_nom.sel(name=battery.DISCHARGER) - ratio * e == 0, name="battery_discharger_size")

    status, _ = n.optimize(solver_name="highs", log_to_console=False, io_api="direct", extra_functionality=extra)
    return (n if status == "ok" else None), terms


def _sizes(n: pypsa.Network, s: System, plan: dict, terms: dict | None) -> dict:
    out = {}
    for b, fixed in plan.items():
        if fixed is not None:
            out[b] = fixed
        elif b == "ng_boiler":   # rounded up, so that the size found still covers the demand
            out[b] = float(math.ceil(n.links.at[ng_boiler.LINK, "p_nom_opt"] * s.boiler.efficiency - 1e-6))
        elif b == "thermal_storage":
            out[b] = float(round(n.stores.at[thermal_storage.STORE, "e_nom_opt"]))
        else:
            out[b] = float(round(n.stores.at[battery.STORE, "e_nom_opt"] / terms["k_e"]))
    return out


def _solution(s: System, regime: str, plan: dict, b_ref: float, b_max: float, dup_lock: str | None, log) -> dict:
    n, terms = _network(s, regime, plan, b_ref, b_max, dup_lock)
    if n is None:
        raise RuntimeError(f"The joint sizing could not be solved (regime {regime}).")
    sizes = _sizes(n, s, plan, terms)
    res = dispatch.results(n, s)
    heat = dispatch.heat_results(n, s) if s.boiler is not None else None
    del n
    gc.collect()
    grid = costs.grid_part(res, s, regime)
    cost = costs.yearly(s, grid, heat, sizes, ems_yr=0.0 if sizes.get("battery") else None)
    dup = s.grid.tariff.dup(res["grid_import"], s.grid.hp_mask.reindex(res.index), s.dt)
    log("    " + ", ".join(f"{NAMES[b]} {v:,.0f} {UNITS[b]}" for b, v in sizes.items())
        + f"  ->  {cost['total']:,.0f}/yr  (regime {regime}{', DUP held' if dup_lock else ''}, DUP {dup:,.0f} h)")
    return {"sizes": sizes, "regime": regime, "dup_lock": dup_lock, "dup": dup, "res": res, "heat": heat,
            "grid": grid, "cost": cost}


def optimise(s: System, base: str, plan: dict, b_max: float, log=print) -> dict:
    """The cheapest sizes for one plan: under the starting regime, and in each regime with the DUP held when the
    result's DUP crosses the threshold (with a battery); repeated once at the battery size found when its linear
    terms differ there."""
    t = s.grid.tariff

    def in_regimes(b_ref):
        best = _solution(s, base, plan, b_ref, b_max, None, log)
        if "battery" in plan and t.rule and t.regime_of(best["dup"]) != base:
            other = t.other_regime(base)
            log(f"    DUP crosses {t.dup_threshold_h:,} h: solved again with the DUP held in regime {base} and in {other}")
            options = [_solution(s, base, plan, b_ref, b_max, base, log),
                       _solution(s, other, plan, b_ref, b_max, other, log)]
            best = min(options, key=lambda o: o["cost"]["total"])
        return best

    best = in_regimes(b_max)
    if plan.get("battery", 0) is None:
        found = best["sizes"]["battery"]
        if found >= 1:
            a, b = battery_terms(s, b_max), battery_terms(s, found)
            meter, _ = dispatch.exclusive_steps(s, best["regime"])
            changed = any(abs(a[k] - b[k]) > 0.01 * max(abs(a[k]), 1e-9) for k in a)
            if changed or (len(meter) and abs(found - b_max) > 0.05 * b_max):
                log(f"    battery terms taken again at {found:,.0f} kWh")
                best = in_regimes(found)
    return best


def run(s: System, blocks: dict, *, regime_auto: bool = True, regime_manual: str | None = None, log=print) -> dict:
    """Joint sizing of the system's sized blocks, then each left out once. Sets s.boiler_kw and s.storage_kwh to the
    sizes found; the battery's size is in the result (its study runs at that size)."""
    plan = plan_of(s, blocks)
    base, _ = dispatch.choose_regime(s, regime_auto, regime_manual)
    b_max = battery_limit(s, blocks) if s.battery is not None else 0.0
    log("\n=== JOINT SIZING ===")
    log("  Sized together: " + (", ".join(NAMES[b] for b, v in plan.items() if v is None) or "none")
        + ("; fixed: " + ", ".join(f"{NAMES[b]} {v:,.0f} {UNITS[b]}" for b, v in plan.items() if v is not None)
           if any(v is not None for v in plan.values()) else "")
        + (f"; battery at most {b_max:,.0f} kWh" if "battery" in plan else ""))
    best = optimise(s, base, plan, b_max, log)

    log("\n=== JOINT SIZING: EACH BLOCK LEFT OUT ===")
    without, notes = {}, []
    for b in plan:
        if b == "ng_boiler":   # the only heat source: the system cannot do without it
            continue
        log(f"  Without the {NAMES[b]}:")
        without[b] = optimise(s, base, {k: v for k, v in plan.items() if k != b}, b_max, log)

    # each block's value: the site's yearly cost without it minus with it, both without the battery's EMS costs (the
    # same battery in both, since nothing links it to the heat side yet)
    value = {b: w["cost"]["total"] - best["cost"]["total"] for b, w in without.items() if b != "battery"}
    # the battery with its EMS costs (a share of its bill saving): kept only if the site is still cheaper with it
    if best["sizes"].get("battery"):
        bill_without = without["battery"]["grid"]["bill"]
        best["cost"] = costs.yearly(s, best["grid"], best["heat"], best["sizes"], bill_without_battery=bill_without)
        if best["cost"]["total"] >= without["battery"]["cost"]["total"]:
            notes.append(f"The battery found ({best['sizes']['battery']:,.0f} kWh) does not pay for its EMS costs: the "
                         "site is cheaper without it, so it is left out.")
            log("  " + notes[-1])
            kept = dict(without["battery"])
            kept["sizes"] = {**kept["sizes"], "battery": 0.0}
            best = kept
    if "battery" in without:
        value["battery"] = without["battery"]["cost"]["total"] - best["cost"]["total"]
    for b in list(plan):
        if b in best["sizes"] and best["sizes"][b] < 1 and plan[b] is None:
            best["sizes"][b] = 0.0
            if not any(NAMES[b] in note for note in notes):
                notes.append(f"The {NAMES[b]} is not worth installing: the joint sizing gives it no size.")
    for b, v in value.items():
        log(f"  Value of the {NAMES[b]} in the system: {v:,.0f}/yr")
    s.boiler_kw = best["sizes"].get("ng_boiler", s.boiler_kw)
    s.storage_kwh = best["sizes"].get("thermal_storage", s.storage_kwh)
    log("  Joint sizes: " + ", ".join(f"{NAMES[b]} {v:,.0f} {UNITS[b]}" for b, v in best["sizes"].items())
        + f";  yearly cost of the site {best['cost']['total']:,.0f}")
    return {"plan": plan, "sizes": best["sizes"], "regime": best["regime"], "dup_lock": best["dup_lock"],
            "cost": best["cost"], "heat": best["heat"], "res": best["res"], "value": value, "notes": notes,
            "without": {b: {"sizes": w["sizes"], "cost": w["cost"], "heat": w["heat"]} for b, w in without.items()},
            "battery_max_kwh": b_max if "battery" in plan else None}
