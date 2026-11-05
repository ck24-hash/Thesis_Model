"""With and without each technology: what every block the system could do without brings to the site.

For each such block X (not the greenhouse or the grid, not a block that only follows another like the gas supply):
the system without X, and without what cannot run without it (a heat storage without a heat source), is sized again
together (system/joint.py) and its yearly cost set against the system with X. X is not evaluated when leaving it out
would leave the heat or CO2 demand without a source (the gas boiler or the heat pump when it is the only heat source):
that system would not model the demand and look cheaper than it is.

Both systems are counted the same way (system/costs.py, from the optimised year). A system without X that keeps a
battery checks that it pays for its EMS costs (joint.optimise_with_ems, quick): nothing more to solve when its sizing
shows it (the battery at its limit saves more than them), else the year without the battery with the other sizes
kept; a battery that does not pay for them is left out there too. Then, for X:

    effect on a line of the yearly cost   with - without   (below 0: X lowers it)
    effect on the yearly cost             YC_without - YC_with   (above 0: X lowers the site's yearly cost)
    extra investment                      what the system with X invests more (full investments)
    running saving                        running_without - running_with
    payback                               extra investment / running saving
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from system import dispatch, flows, joint, setup
from system.setup import System

FIGURES = [   # key figure, which way is better for the site ("" = neither)
    ("PV production (MWh)", "higher"), ("Self-consumption (%)", "higher"), ("Self-sufficiency (%)", "higher"),
    ("Grid import (MWh)", "lower"), ("Grid export (MWh)", ""), ("Grid bill", "lower"), ("Gas (MWh)", "lower"),
    ("CO2 emitted (t)", "lower"), ("CO2 bought (t)", ""), ("Heat pump heat (MWh)", ""), ("Heat pump electricity (MWh)", ""),
    ("Heat unmet (MWh)", "lower"), ("CO2 unmet (t)", "lower")]


def removable(blocks) -> list[str]:
    """The blocks the system could do without: built, not always in, not following another block."""
    return [b for b in blocks if b in setup.BLOCKS and not setup.CATALOGUE[b].get("fixed")
            and not setup.CATALOGUE[b].get("follows")]


def lost_demand(blocks, kept) -> str | None:
    """Why the system cannot do without the blocks taken out: a demand left without a source."""
    for carrier, demand in (("heat", "heat"), ("co2", "CO2")):
        had = setup.sources(blocks, carrier)
        if had and not setup.sources(kept, carrier):
            return (f"without it the greenhouse's {demand} demand has no source "
                    f"({' or '.join(setup.CATALOGUE[b]['name'].lower() for b in had)} is the only one)")
    return None


def _with_ems(cost: dict, ems: float | None) -> dict:
    """The yearly cost with the battery's EMS costs set to `ems` (when the system has a battery)."""
    if ems is None or "Battery: EMS" not in cost["running"]:
        return cost
    running = {**cost["running"], "Battery: EMS": ems}
    total = sum(running.values())
    return {**cost, "running": running, "running_total": total, "total": total + cost["investment_total"]}


def _figures(sol: dict, s: System) -> dict:
    sc = flows.sc_ss(sol["res"], s)
    other = sol["cost"]["other"]
    return {"PV production (MWh)": sc["total_pv"], "Self-consumption (%)": sc["sc_pct"],
            "Self-sufficiency (%)": sc["ss_pct"], "Grid import (MWh)": other["Grid import (MWh)"],
            "Grid export (MWh)": other["Grid export (MWh)"], "Grid bill": sol["grid"]["bill"],
            **{k: v for k, v in other.items() if k in dict(FIGURES)}}


def compare(with_sol: dict, with_cost: dict, s: System, without_sol: dict, without_cost: dict, s_without: System) -> dict:
    """One technology: its effect on each line of the yearly cost and on the key figures."""
    rows = []
    for part, key in (("Running", "running"), ("Investment per year", "investment")):
        for item in dict.fromkeys(list(with_cost[key]) + list(without_cost[key])):
            a, b = with_cost[key].get(item, 0.0), without_cost[key].get(item, 0.0)
            rows.append({"Part": part, "Item": item, "With": a, "Without": b, "Effect": a - b})
        total = "running_total" if key == "running" else "investment_total"
        rows.append({"Part": part, "Item": f"Total {part.lower()}", "With": with_cost[total],
                     "Without": without_cost[total], "Effect": with_cost[total] - without_cost[total]})
    rows.append({"Part": "Total", "Item": "Yearly cost of the site", "With": with_cost["total"],
                 "Without": without_cost["total"], "Effect": with_cost["total"] - without_cost["total"]})
    fa, fb = _figures(with_sol, s), _figures(without_sol, s_without)
    figures = [{"Figure": f"Size: {joint.NAMES.get(k, k)}", "With": with_sol["sizes"].get(k, 0.0),
                "Without": without_sol["sizes"].get(k, 0.0), "Better": ""}
               for k in dict.fromkeys(list(with_sol["sizes"]) + list(without_sol["sizes"]))]
    figures += [{"Figure": name, "With": fa.get(name, 0.0), "Without": fb.get(name, 0.0), "Better": better}
                for name, better in FIGURES if name in fa or name in fb]
    invested_with, invested_without = sum(with_cost["invested"].values()), sum(without_cost["invested"].values())
    extra = invested_with - invested_without
    saving = without_cost["running_total"] - with_cost["running_total"]
    return {"evaluated": True, "costs": pd.DataFrame(rows), "figures": pd.DataFrame(figures),
            "total_with": with_cost["total"], "total_without": without_cost["total"],
            "difference": without_cost["total"] - with_cost["total"],
            "invested_with": invested_with, "invested_without": invested_without, "extra_investment": extra,
            "running_saving": saving, "payback_yr": extra / saving if extra > 0 and saving > 0 else None,
            "sizes_without": without_sol["sizes"], "heat_without": without_sol["heat"]}


def run(s: System, case: dict, case_dir: Path, out: dict, *, regime_auto: bool = True, regime_manual: str | None = None,
        log=print) -> dict:
    """With and without each technology the system could do without (the module's docstring). out: the run so far
    (its joint sizing)."""
    blocks = case["blocks"]
    j = out["joint"]
    log("\n=== WITH AND WITHOUT EACH TECHNOLOGY ===")
    with_sol = j["best"]   # the system with every technology
    with_cost = _with_ems(with_sol["cost"], j["cost"]["running"].get("Battery: EMS"))

    effects = {}
    for x in removable(blocks):
        kept, also = setup.leave_out(list(blocks), [x])
        name = setup.CATALOGUE[x]["name"]
        why = lost_demand(blocks, kept)
        if why:
            effects[x] = {"evaluated": False, "name": name, "reason": why, "also": []}
            log(f"  {name}: not evaluated, {why}")
            continue
        log(f"  Without the {name.lower()}" + (f" (and {', '.join(also)})" if also else "") + ":")
        if x in j["without"] and not also:
            s_x, sol = s, j["without"][x]   # solved by the joint sizing's EMS check
        else:
            case_x = {**case, "blocks": {k: v for k, v in blocks.items() if k in kept}}
            s_x = setup.build(case_x, case_dir)
            base_x, _ = dispatch.choose_regime(s_x, regime_auto, regime_manual)
            sol, _, _ = joint.optimise_with_ems(s_x, base_x, joint.plan_of(s_x, case_x["blocks"]),
                                                joint.battery_limit(s_x, blocks) if s_x.battery else 0.0, log,
                                                quick=True)
        effects[x] = {"name": name, "also": also, **compare(with_sol, with_cost, s, sol, sol["cost"], s_x)}
        log(f"    {name}: the site's yearly cost is {effects[x]['difference']:,.0f} lower with it")
    return effects
