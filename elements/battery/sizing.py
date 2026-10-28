"""Battery sizing: solve a list of sizes, and pick one by lifetime profit, payback or a custom size (from
elements/battery_reference engine/sizing.py).

Each size is solved under the no-battery regime. When its DUP lands in the other regime, that bill is not what the
utility would charge, so the size is solved twice more (DUP held inside the no-battery regime, and under the other
regime with its DUP held there) and the better one is kept. The value is always measured against the no-battery
bill. A size's yearly value is its bill saving + ancillary revenue - EMS costs (fixed and fees); its investment is
the net battery price + the EMS capex.
"""
from __future__ import annotations

import gc

import pandas as pd

from common.money import lifetime_profit, payback_years
from system import dispatch
from system.setup import System

DEFAULTS = {
    "objective": "profit",            # profit: max lifetime profit; payback: min payback; custom: custom_kwh
    "custom_kwh": 422,
    "sweep_kwh": list(range(100, 1501, 100)),
    "fine_grid_kwh": [],              # no fine stage; a case may give sizes here to refine around the best size
    "fine_window_kwh": 250,
    "cap_at_subsidy_size": True,      # with a threshold subsidy (CH's OCAN rule), only sizes up to the subsidised
                                      # maximum, that maximum always tested
}


def evaluate_size(s: System, size_kwh: float, regime: str, baseline_op_cost: float,
                  dup_lock: str | None = None, log=print, dispatches: dict | None = None) -> dict | None:
    """Solve one size and return its yearly value, payback, SC, SS and DUP. With `dispatches`, its dispatch table is
    kept there under (size, regime, dup_lock or ""), so the pipeline need not solve the chosen size again."""
    log(f"  {size_kwh:>6} kWh ...", end="")
    n = dispatch.solve(s, regime, battery_kwh=size_kwh, dup_lock=dup_lock)
    if n is None:
        log(" FAILED")
        return None
    dt, load = s.dt, s.load
    imp = n.generators_t.p["grid_import"]
    exp = -n.generators_t.p["grid_export"]
    hp = s.grid.hp_mask.reindex(n.snapshots)
    demand = s.grid.tariff.yearly_capacity_charge(imp, regime)
    net = s.bm.pv_net_revenue(exp).sum() - (imp * s.import_price(regime) * dt).sum() - demand
    bill_saving = net + baseline_op_cost
    ancillary = s.ancillary_revenue(size_kwh)
    ems = s.ems.fees(ancillary, bill_saving)
    value = bill_saving + ancillary - ems["total"]
    investment = s.battery_investment(size_kwh)
    pb = payback_years(investment, value)
    ss = (1 - imp.sum() / load.sum()) * 100
    pv_ts = dispatch.pv_output(n, s)
    charge = n.links_t.p0["bat_charger"]
    surplus = (pv_ts - n.loads_t.p_set["load"]).clip(lower=0)
    from_pv = surplus.clip(upper=charge)
    pv_kwh = pv_ts.sum() * dt
    sc = ((pv_kwh - surplus.sum() * dt) + from_pv.sum() * dt * s.eta2) / pv_kwh * 100 if pv_kwh > 0 else 0.0
    dup = s.grid.tariff.dup(imp, hp, dt)
    if dispatches is not None:
        dispatches[(size_kwh, regime, dup_lock or "")] = dispatch.results(n, s)
    del n, imp, exp, pv_ts, charge, surplus, from_pv
    gc.collect()   # a solved network holds reference cycles: without this, memory grows by about 0.5 GB per size
    log(f" val={value:,.0f}/yr  pb={pb:.1f} yr  SS={ss:.1f}%  SC={sc:.1f}%  DUP={dup:,.0f} h "
        f"(regime {regime}{', DUP held' if dup_lock else ''})")
    return dict(size=size_kwh, bat_value=value, investment=investment, payback=pb, ss=ss, sc=sc,
                lifetime_profit=lifetime_profit(value, s.commercial.battery_life_yr, investment),
                ems_fees=ems["voltiris"] + ems["external"],
                dup=dup, regime=regime, dup_lock=dup_lock or "")


def evaluate_size_any_regime(s: System, size_kwh: float, base_regime: str, baseline_op_cost: float,
                             log=print, dispatches: dict | None = None) -> dict | None:
    r = evaluate_size(s, size_kwh, base_regime, baseline_op_cost, log=log, dispatches=dispatches)
    if r is None or not s.grid.tariff.rule or s.grid.tariff.regime_of(r["dup"]) == base_regime:
        return r   # without a regime rule (NL, FR) the regime is the one the case chose
    other = s.grid.tariff.other_regime(base_regime)
    log(f"    DUP {r['dup']:,.0f} h crosses {s.grid.tariff.dup_threshold_h:,} h -> re-solving with DUP held in "
        f"regime {base_regime}, and under regime {other}")
    options = []
    log("  ", end="")
    options.append(evaluate_size(s, size_kwh, base_regime, baseline_op_cost, dup_lock=base_regime, log=log,
                                 dispatches=dispatches))
    log("  ", end="")
    options.append(evaluate_size(s, size_kwh, other, baseline_op_cost, dup_lock=other, log=log,
                                 dispatches=dispatches))
    options = [o for o in options if o is not None]
    if not options:
        return None
    best = max(options, key=lambda o: o["bat_value"])
    log(f"    -> keep regime {best['regime']}  (DUP {best['dup']:,.0f} h, val={best['bat_value']:,.0f}/yr)")
    return best


def choose(table: pd.DataFrame, objective: str, custom_kwh: float, battery_life_yr: float) -> int:
    """The chosen size: max lifetime profit among sizes that pay back within the battery life (else min payback),
    min payback, or the size closest to custom_kwh."""
    if objective == "profit":
        valid = table[table["payback"] <= battery_life_yr]
        return int(valid["lifetime_profit"].idxmax()) if not valid.empty else int(table["payback"].idxmin())
    if objective == "custom":
        return int(min(table.index, key=lambda size: abs(size - custom_kwh)))
    return int(table["payback"].idxmin())


def sweep(s: System, base_regime: str, baseline_op_cost: float, settings: dict | None = None,
          log=print, dispatches: dict | None = None) -> pd.DataFrame:
    """Two stages: the coarse sizes, then the fine grid around the best coarse size. One row per size. With
    `dispatches`, every solved size's dispatch table is kept there (see evaluate_size)."""
    cfg = {**DEFAULTS, **(settings or {})}
    life = s.commercial.battery_life_yr
    coarse = sorted(set(cfg["sweep_kwh"]) | ({cfg["custom_kwh"]} if cfg["objective"] == "custom" else set()))
    cap = None
    if cfg["cap_at_subsidy_size"] and s.subsidies.cap_sweep_at_subsidy:
        cap = round(s.subsidies.battery_threshold_kwh)
        coarse = sorted({size for size in coarse if size <= cap} | {cap})
    log(f"Stage 1  coarse: {coarse} kWh")
    rows = [r for r in (evaluate_size_any_regime(s, size, base_regime, baseline_op_cost, log=log,
                                                 dispatches=dispatches) for size in coarse)
            if r is not None]
    table = pd.DataFrame(rows).set_index("size")
    best = choose(table, cfg["objective"], cfg["custom_kwh"], life)
    log(f"\n  Best coarse: {best} kWh  ({table.loc[best, 'payback']:.1f} yr payback)\n")
    fine = [size for size in cfg["fine_grid_kwh"]
            if abs(size - best) <= cfg["fine_window_kwh"] and size not in table.index
            and (cap is None or size <= cap)]
    if fine:
        log(f"Stage 2  fine grid near {best} kWh: {fine}")
        rows = [r for r in (evaluate_size_any_regime(s, size, base_regime, baseline_op_cost, log=log,
                                                     dispatches=dispatches)
                            for size in fine) if r is not None]
        if rows:
            table = pd.concat([table, pd.DataFrame(rows).set_index("size")]).sort_index()
    return table
