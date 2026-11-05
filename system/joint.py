"""Joint sizing: the sizes of every sized block chosen together in one optimisation (PyPSA capacity expansion), for the
lowest yearly cost of the whole site: running costs (grid, gas, carbon levy, variable O&M) + each investment spread
over its life + fixed O&M - the battery's ancillary revenue. It is the rule of each block's own study (lifetime
profit, lifetime cost) applied to all of them at once, so a block that lets another be smaller is valued for it (a
heat storage that lets the boiler be smaller).

The sized blocks: the gas boiler (kW of heat), the heat pump (kW of heat), the heat storage (kWh of heat), the
battery (kWh bought). A block whose sizing objective is "custom" keeps that size (0: not installed). When a heat
source's size is free the heat demand must be met (no slack), and when the boiler's is free the CO2 demand too.

Exact in the optimisation: the boiler, the heat pump and the heat storage (linear prices and O&M; the heat pump's
size is its most heat, its electricity at most size / COP at each step). Approximated, then checked:
- the battery's price per kWh (tiers, subsidy), usable share and reserve are taken at a reference size (the largest
  allowed), and the optimisation is repeated once at the size found when they differ there;
- the battery's EMS costs (fixed, fees on the saving) are not in it: the battery is kept only if it still lowers the
  site's yearly cost with them (optimise_with_ems; a fixed size is kept). In the systems without a technology the
  check is shorter (quick): skipped when the solve shows the battery pays, else against the year without it with the
  other sizes kept;
- under EaaS, the heat pump's import during a PV surplus is limited with its draw at the start size (the fixed size,
  else the heat demand's peak), exact once the size is fixed (system/dispatch.py);
- the battery is at most the subsidised maximum (cap_at_subsidy_size, CH) or the largest size of its list;
- the one-meter rules use the reference size's battery power (they apply only where exporting pays more than
  importing, or prices are negative; never in CH);
- the regime (CH): solved under the starting regime; with a battery or a heat pump (both change what is drawn from
  the grid), when the result's DUP crosses the threshold, solved again with the DUP held in each regime, and the
  cheaper kept (as the battery study does).

What each block is worth to the site, with and without it, is in system/effects.py.
"""
from __future__ import annotations

import gc
import math

import pypsa

from elements.battery import block as battery
from elements.battery import sizing as battery_sizing
from elements.gas_supply import block as gas_supply
from elements.heat_pump import block as heat_pump
from elements.ng_boiler import block as ng_boiler
from elements.thermal_storage import block as thermal_storage
from system import costs, dispatch
from system.setup import System

SIZED = ("ng_boiler", "heat_pump", "thermal_storage", "battery")
HEAT_SOURCES = ("ng_boiler", "heat_pump")
NAMES = {"ng_boiler": "gas boiler", "heat_pump": "heat pump", "thermal_storage": "heat storage", "battery": "battery"}
UNITS = {"ng_boiler": "kW", "heat_pump": "kW", "thermal_storage": "kWh", "battery": "kWh"}


def plan_of(s: System, blocks: dict) -> dict:
    """The sized blocks of the system: block -> its fixed size (objective "custom") or None (sized here)."""
    present = {"ng_boiler": s.boiler, "heat_pump": s.heat_pump, "thermal_storage": s.storage, "battery": s.battery}
    key = {"ng_boiler": "custom_kw", "heat_pump": "custom_kw", "thermal_storage": "custom_kwh", "battery": "custom_kwh"}
    plan = {}
    for b in SIZED:
        if present[b] is None:
            continue
        cfg = (blocks.get(b) or {}).get("sizing") or {}
        plan[b] = float(cfg[key[b]]) if cfg.get("objective") == "custom" and cfg.get(key[b]) is not None else None
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
    bought (first purchase after subsidy and replacements over the PV life: costs.battery_per_year, without the EMS
    hardware) and the ancillary revenue per kWh bought."""
    t = s.battery.tech
    return {"k_e": t.dispatch_kwh(size) / size, "k_p": t.dispatch_kw(size) / size,
            "cost": costs.battery_per_year(s, size, ems_hardware=False) / size,
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
        boiler_kw = (plan["ng_boiler"] if plan.get("ng_boiler") is not None
                     else float(s.greenhouse.heat.max()))   # a start value when it is free
    hp_kw = None
    if s.heat_pump is not None:
        hp_kw = plan["heat_pump"] if plan.get("heat_pump") is not None else float(s.greenhouse.heat.max())
    storage_kwh = 0.0 if "thermal_storage" not in plan else (
        plan["thermal_storage"] if plan["thermal_storage"] is not None else 1.0)
    battery_kwh = (None if "battery" not in plan or plan["battery"] == 0
                   else plan["battery"] if plan["battery"] is not None else b_ref)
    n = pypsa.Network()
    dispatch._add_components(n, s, regime, battery_kwh, boiler_kw, storage_kwh,
                             heat_slack=not free & set(HEAT_SOURCES), co2_slack="ng_boiler" not in free,
                             heat_pump_kw=hp_kw)
    dispatch.meter_bounds(n, s, regime, battery_kwh)
    terms = None
    if free & {"ng_boiler", "heat_pump", "thermal_storage"}:   # what follows the heat blocks' sizes is free of cost
        _extendable(n.generators, "heat_release", "p_nom", 0.0)
    if "heat_pump" in free:   # p_nom is kW of electricity at the lowest COP: x lowest COP = kW of heat
        per_kw_th = c.heat_pump_capex(1.0) / c.heat_pump_life_yr + c.heat_pump_fixed_om(1.0)
        _extendable(n.links, heat_pump.LINK, "p_nom", per_kw_th * s.heat_pump.cop_min)
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
        elif b == "heat_pump":   # rounded up, as the boiler
            out[b] = float(math.ceil(n.links.at[heat_pump.LINK, "p_nom_opt"] * s.heat_pump.cop_min - 1e-6))
        elif b == "thermal_storage":
            out[b] = float(round(n.stores.at[thermal_storage.STORE, "e_nom_opt"]))
        else:
            out[b] = float(round(n.stores.at[battery.STORE, "e_nom_opt"] / terms["k_e"]))
    return out


def _limit_gain(n: pypsa.Network, terms: dict | None) -> float | None:
    """With the battery sized: what it saves per year at least beyond its own cost, its usable kWh times the value of
    one more kWh of its limit (the limit's shadow price; 0 below the limit). The site's cost as a function of the
    battery's size is convex in a linear programme, so the saving from 0 to the size found is at least its slope there."""
    if terms is None or "Store-ext-e_nom-upper" not in n.model.constraints:
        return None
    dual = n.model.constraints["Store-ext-e_nom-upper"].dual.to_series().get(battery.STORE)
    if dual is None:
        return None
    return max(-float(dual), 0.0) * float(n.stores.at[battery.STORE, "e_nom_opt"])


def _solution(s: System, regime: str, plan: dict, b_ref: float, b_max: float, dup_lock: str | None, log) -> dict:
    n, terms = _network(s, regime, plan, b_ref, b_max, dup_lock)
    if n is None:
        raise RuntimeError(f"The joint sizing could not be solved (regime {regime}).")
    limit_gain = _limit_gain(n, terms)
    sizes = _sizes(n, s, plan, terms)
    res = dispatch.results(n, s)
    heat = dispatch.heat_results(n, s) if s.heat_side else None
    del n
    gc.collect()
    grid = costs.grid_part(res, s, regime)
    cost = costs.yearly(s, grid, heat, sizes, ems_yr=0.0 if sizes.get("battery") else None)
    dup = s.grid.tariff.dup(res["grid_import"], s.grid.hp_mask.reindex(res.index), s.dt)
    log("    " + ", ".join(f"{NAMES[b]} {v:,.0f} {UNITS[b]}" for b, v in sizes.items())
        + f"  ->  {cost['total']:,.0f}/yr  (regime {regime}{', DUP held' if dup_lock else ''}, DUP {dup:,.0f} h)")
    return {"sizes": sizes, "regime": regime, "dup_lock": dup_lock, "dup": dup, "res": res, "heat": heat,
            "grid": grid, "cost": cost, "limit_gain": limit_gain}


def optimise(s: System, base: str, plan: dict, b_max: float, log=print) -> dict:
    """The cheapest sizes for one plan: under the starting regime, and in each regime with the DUP held when the
    result's DUP crosses the threshold (with a battery); repeated once at the battery size found when its linear
    terms differ there."""
    t = s.grid.tariff

    def in_regimes(b_ref):
        best = _solution(s, base, plan, b_ref, b_max, None, log)
        if ("battery" in plan or s.heat_pump is not None) and t.rule and t.regime_of(best["dup"]) != base:
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


def _pays_at_limit(s: System, base: str, best: dict, log) -> bool:
    """True when the solve itself shows that the battery pays for its EMS costs, so the year without it is not needed:
    no fee on the bill saving (else the saving is needed), the solve under the starting regime with no DUP held, the
    year without battery then solved the same way (no heat pump moving the DUP, or no regime rule), and the battery's
    least saving beyond its own cost (_limit_gain) at least its EMS costs (fees, and the EMS hardware over the PV
    life). Then sets the solution's yearly cost with them."""
    size = best["sizes"]["battery"]
    if any(s.ems.savings_pct.values()) or best.get("limit_gain") is None:
        return False
    if best["regime"] != base or best["dup_lock"] or (s.heat_pump is not None and s.grid.tariff.rule):
        return False
    fees = s.ems.fees(s.ancillary_revenue(size), 0.0)["total"]
    ems = fees + costs.battery_per_year(s, size) - costs.battery_per_year(s, size, ems_hardware=False)
    if best["limit_gain"] < ems:
        return False
    best["cost"] = costs.yearly(s, best["grid"], best["heat"], best["sizes"], ems_yr=fees)
    log(f"  Battery (its EMS check): at its limit it saves at least {best['limit_gain']:,.0f}/yr beyond its own cost, "
        f"more than its EMS costs ({ems:,.0f}/yr); no year without it needed")
    return True


def optimise_with_ems(s: System, base: str, plan: dict, b_max: float, log=print,
                      quick: bool = False) -> tuple[dict, dict | None, str | None]:
    """optimise(), with the battery's EMS costs in the yearly cost. They are a share of its bill saving, so the system
    is optimised without the battery too; a battery sized here is kept only if the site is still cheaper with them (a
    fixed size is kept). Returns (the solution, the solution without the battery or None, a note or None).

    quick (the systems without a technology, system/effects.py): no year without the battery when the solve shows it
    pays (_pays_at_limit; a fixed size with no fee on the saving needs none either); else that year with the other
    sizes kept, not sized again (one year's operation). Only a battery that does not pay even then is checked with the
    other sizes free, so a battery left out is always left out against the best system without it."""
    best = optimise(s, base, plan, b_max, log)
    if not best["sizes"].get("battery"):
        return best, None, None
    fixed_battery = plan["battery"] is not None
    if quick:
        no_fee = not any(s.ems.savings_pct.values())
        if fixed_battery and no_fee:
            best["cost"] = costs.yearly(s, best["grid"], best["heat"], best["sizes"],
                                        ems_yr=s.ems.fees(s.ancillary_revenue(best["sizes"]["battery"]), 0.0)["total"])
            return best, None, None
        if not fixed_battery and _pays_at_limit(s, base, best, log):
            return best, None, None
        log("  Without the battery, the other sizes kept (its EMS check):")
        kept = {k: best["sizes"][k] for k in plan if k != "battery"}
        without = optimise(s, base, kept, b_max, log)
    else:
        log("  Without the battery (its EMS check):")
        without = optimise(s, base, {k: v for k, v in plan.items() if k != "battery"}, b_max, log)
    best["cost"] = costs.yearly(s, best["grid"], best["heat"], best["sizes"],
                                bill_without_battery=without["grid"]["bill"])
    if not fixed_battery and best["cost"]["total"] >= without["cost"]["total"]:
        if quick:   # the other sizes free: only cheaper without the battery, so it is left out there too
            log("  Without the battery, the other sizes free:")
            without = optimise(s, base, {k: v for k, v in plan.items() if k != "battery"}, b_max, log)
        note = (f"The battery found ({best['sizes']['battery']:,.0f} kWh) does not pay for its EMS costs: the site is "
                "cheaper without it, so it is left out.")
        log("  " + note)
        return {**without, "sizes": {**without["sizes"], "battery": 0.0}}, without, note
    return best, without, None


def run(s: System, blocks: dict, *, regime_auto: bool = True, regime_manual: str | None = None, log=print) -> dict:
    """Joint sizing of the system's sized blocks. Sets s.boiler_kw, s.heat_pump_kw and s.storage_kwh to the sizes
    found; the battery's size is in the result (its study runs at that size). With a battery, the system without it is
    optimised too (optimise_with_ems): a battery sized here is kept only if the site is still cheaper with its EMS
    costs (a share of its bill saving)."""
    plan = plan_of(s, blocks)
    base, _ = dispatch.choose_regime(s, regime_auto, regime_manual)
    b_max = battery_limit(s, blocks) if s.battery is not None else 0.0
    log("\n=== JOINT SIZING ===")
    log("  Sized together: " + (", ".join(NAMES[b] for b, v in plan.items() if v is None) or "none")
        + ("; fixed: " + ", ".join(f"{NAMES[b]} {v:,.0f} {UNITS[b]}" for b, v in plan.items() if v is not None)
           if any(v is not None for v in plan.values()) else "")
        + (f"; battery at most {b_max:,.0f} kWh" if "battery" in plan else ""))
    best, without_battery, note = optimise_with_ems(s, base, plan, b_max, log)
    notes = [note] if note else []
    without = {"battery": without_battery} if without_battery is not None else {}
    for b in list(plan):
        if b in best["sizes"] and best["sizes"][b] < 1 and plan[b] is None:
            best["sizes"][b] = 0.0
            if not any(NAMES[b] in note for note in notes):
                notes.append(f"The {NAMES[b]} is not worth installing: the joint sizing gives it no size.")
    s.boiler_kw = best["sizes"].get("ng_boiler", s.boiler_kw)
    s.heat_pump_kw = best["sizes"].get("heat_pump", s.heat_pump_kw)
    s.storage_kwh = best["sizes"].get("thermal_storage", s.storage_kwh)
    log("  Joint sizes: " + ", ".join(f"{NAMES[b]} {v:,.0f} {UNITS[b]}" for b, v in best["sizes"].items())
        + f";  yearly cost of the site {best['cost']['total']:,.0f}")
    return {"plan": plan, "sizes": best["sizes"], "regime": best["regime"], "dup_lock": best["dup_lock"],
            "cost": best["cost"], "heat": best["heat"], "res": best["res"], "best": best, "without": without,
            "notes": notes, "battery_max_kwh": b_max if "battery" in plan else None}
