"""Two scenarios of one case: A, the case as it is, and B, the same case without some of its blocks ("compare":
{"without": [...]}). B can only take blocks out, never add: what cannot run without them is taken out too (a heat
storage without a heat source, a gas supply without a block that burns gas; common/blocks.json). B is sized and run
like A (same market, inputs, parameters and sizing mode), then the two are compared on the site's yearly cost:

    difference            B - A for each line of the yearly cost, running and investment per year
    extra investment      what A invests more than B (full investments, not per year)
    running saving        what A saves per year in running costs against B
    payback               extra investment / running saving (when A invests more and runs cheaper)

and on the sizes and the key figures (electricity, gas, CO2).
"""
from __future__ import annotations

import pandas as pd

from system import setup

NAMES = {b: c["name"] for b, c in setup.CATALOGUE.items()}


def case_b(case: dict, without: list[str]) -> tuple[dict, list[str]]:
    """Scenario B's case, and the blocks taken out with those asked."""
    kept, also = setup.leave_out(list(case["blocks"]), without)
    b = {**case, "blocks": {k: v for k, v in case["blocks"].items() if k in kept}}
    b.pop("compare", None)
    return b, also


def _final_kpi(out: dict) -> dict:
    cases = out["electricity"]["cases"]
    return cases["battery" if "battery" in cases else "no_battery"]["kpi"]


def comparison(a: dict, b: dict, without: list[str], also: list[str]) -> dict:
    """A against B (each run_case.run's results)."""
    ca, cb = a["costs"], b["costs"]
    rows = []
    for part, key in (("Running", "running"), ("Investment per year", "investment")):
        for item in dict.fromkeys(list(ca[key]) + list(cb[key])):
            va, vb = ca[key].get(item, 0.0), cb[key].get(item, 0.0)
            rows.append({"Part": part, "Item": item, "A": va, "B": vb, "B - A": vb - va})
        total = "running_total" if key == "running" else "investment_total"
        rows.append({"Part": part, "Item": f"Total {part.lower()}", "A": ca[total], "B": cb[total],
                     "B - A": cb[total] - ca[total]})
    rows.append({"Part": "Total", "Item": "Yearly cost of the site", "A": ca["total"], "B": cb["total"],
                 "B - A": cb["total"] - ca["total"]})
    ka, kb = _final_kpi(a), _final_kpi(b)
    figures = [(f"Size: {NAMES.get(k, k)}", ca["sizes"].get(k, 0.0), cb["sizes"].get(k, 0.0))
               for k in dict.fromkeys(list(ca["sizes"]) + list(cb["sizes"]))]
    figures += [(label, ka[key], kb[key]) for label, key in (
        ("Electricity demand (MWh)", "load_mwh"), ("PV production (MWh)", "pv_mwh"),
        ("Self-consumption (%)", "sc_pct"), ("Self-sufficiency (%)", "ss_pct"), ("Grid import (MWh)", "import_mwh"),
        ("Grid export (MWh)", "export_mwh"), ("Grid bill", "bill"), ("Export revenue", "export_revenue"))]
    figures += [(label, ca["other"].get(key), cb["other"].get(key)) for label, key in (
        ("Gas (MWh)", "Gas (MWh)"), ("CO2 emitted (t)", "CO2 emitted (t)"), ("Heat unmet (MWh)", "Heat unmet (MWh)"),
        ("CO2 unmet (t)", "CO2 unmet (t)")) if key in ca["other"] or key in cb["other"]]
    invested_a, invested_b = sum(ca["invested"].values()), sum(cb["invested"].values())
    extra, saving = invested_a - invested_b, cb["running_total"] - ca["running_total"]
    return {
        "without": without, "also": also, "blocks_a": list(dict.fromkeys(ca["sizes"])),
        "names": {"a": "A: the system as built", "b": "B: without " + ", ".join(NAMES.get(x, x).lower() for x in without)},
        "costs": pd.DataFrame(rows),
        "figures": pd.DataFrame(figures, columns=["Figure", "A", "B"]).assign(**{"B - A": lambda d: d["B"] - d["A"]}),
        "total_a": ca["total"], "total_b": cb["total"], "difference": cb["total"] - ca["total"],
        "invested_a": invested_a, "invested_b": invested_b, "extra_investment": extra, "running_saving": saving,
        "payback_yr": extra / saving if extra > 0 and saving > 0 else None,
    }
