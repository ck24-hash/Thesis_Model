"""How much the chosen sizes matter: each piece of equipment at its chosen size -10 % and +10 %, everything else at its
chosen size, the year's operation solved again (no sizing). One year at the chosen sizes, then two per piece of
equipment: the sized blocks (gas boiler, heat pump, heat storage, battery) when installed, and the Voltiris modules.

Every year is solved the same way (system/dispatch.py, all sizes fixed, the joint sizing's regime) and counted the same
way (system/costs.py; the battery's EMS costs from the bill without battery of the joint sizing). Fixed sizes keep the
heat and CO2 slacks: a size too small to meet the demand shows as unmet heat or CO2, which the yearly cost does not
price; the table shows both.
"""
from __future__ import annotations

import gc
from pathlib import Path

import pandas as pd

from system import costs, dispatch, flows, setup
from system.setup import System

STEP = 0.10
NAMES = {"voltiris": "Voltiris", "ng_boiler": "Gas boiler", "heat_pump": "Heat pump",
         "thermal_storage": "Heat storage", "battery": "Battery"}
UNITS = {"voltiris": "modules", "ng_boiler": "kW", "heat_pump": "kW", "thermal_storage": "kWh", "battery": "kWh"}


def year(s: System, sizes: dict, regime: str, dup_lock: str | None, bill_without_battery: float | None) -> dict | None:
    """The year's operation at fixed sizes: its dispatch, heat side, yearly cost and key figures. None if not solved."""
    kw = dict(boiler_kw=sizes.get("ng_boiler") or 0.0 if s.boiler is not None else None,
              heat_pump_kw=sizes.get("heat_pump") or 0.0 if s.heat_pump is not None else None,
              storage_kwh=sizes.get("thermal_storage") or 0.0,
              battery_kwh=sizes.get("battery") or None if s.battery is not None else None)
    n = dispatch.solve(s, regime, dup_lock=dup_lock, **kw)
    if n is None and dup_lock:
        n = dispatch.solve(s, regime, **kw)
    if n is None:
        return None
    res = dispatch.results(n, s)
    heat = dispatch.heat_results(n, s) if s.heat_side else None
    del n
    gc.collect()
    grid = costs.grid_part(res, s, regime)
    cost = costs.yearly(s, grid, heat, sizes, bill_without_battery=bill_without_battery if sizes.get("battery") else None)
    sc, dt = flows.sc_ss(res, s), s.dt
    fig = {"Grid import (MWh)": grid["import_mwh"], "Grid export (MWh)": grid["export_mwh"],
           "Self-sufficiency (%)": sc["ss_pct"]}
    if heat is not None:
        fig.update({"Gas (MWh)": float(heat["gas"].sum() * dt / 1000),
                    "CO2 emitted (t)": float(heat["co2_emitted"].sum() * dt / 1000),
                    "Heat unmet (MWh)": float(heat["heat_unmet"].sum() * dt / 1000),
                    "CO2 unmet (t)": float(heat["co2_unmet"].sum() * dt / 1000)})
    return {"res": res, "heat": heat, "cost": cost, "figures": fig}


def _row(block: str | None, change: float, size: float | None, y: dict | None, base: dict | None) -> dict:
    row = {"block": block, "equipment": NAMES.get(block, "All at the chosen sizes"), "change_pct": change * 100,
           "size": size, "unit": UNITS.get(block, ""), "solved": y is not None}
    if y is not None:
        c = y["cost"]
        row.update({"yearly_cost": c["total"], "running": c["running_total"], "investment_yr": c["investment_total"],
                    **y["figures"]})
        if base is not None:
            row["yearly_cost_change"] = c["total"] - base["cost"]["total"]
    return row


def run(s: System, case: dict, case_dir: Path, j: dict, log=print) -> dict:
    """The table of the module's docstring, and the year at the chosen sizes (base)."""
    log("\n=== SENSITIVITY: EACH SIZE -10 % AND +10 % ===")
    regime, lock = j["regime"], j["dup_lock"]
    without = (j.get("without") or {}).get("battery")
    bill_nb = without["grid"]["bill"] if without else None
    sizes = {k: v for k, v in j["sizes"].items()}
    log("  The year at the chosen sizes ...")
    base = year(s, sizes, regime, lock, bill_nb)
    if base is None:
        raise RuntimeError("The year at the chosen sizes could not be solved.")
    rows = [_row(None, 0.0, None, base, base)]
    targets = [b for b in ("ng_boiler", "heat_pump", "thermal_storage", "battery") if sizes.get(b)]
    if s.voltiris is not None and s.modules:
        targets.insert(0, "voltiris")
    for b in targets:
        for f in (-STEP, STEP):
            if b == "voltiris":
                modules = max(int(round(s.modules * (1 + f))), 0)
                blocks = {**case["blocks"], "voltiris": {**case["blocks"]["voltiris"], "modules": modules}}
                s_x, sizes_x, size = setup.build({**case, "blocks": blocks}, case_dir), sizes, modules
                for k in ("boiler_kw", "heat_pump_kw", "storage_kwh"):
                    setattr(s_x, k, getattr(s, k))
            else:
                size = sizes[b] * (1 + f)
                s_x, sizes_x = s, {**sizes, b: size}
            log(f"  {NAMES[b]} {f * 100:+.0f} %: {size:,.0f} {UNITS[b]} ...", end="")
            y = year(s_x, sizes_x, regime, lock, bill_nb)
            row = _row(b, f, size, y, base)
            rows.append(row)
            log(" not solved" if y is None else
                f" yearly cost {row['yearly_cost']:,.0f} ({row['yearly_cost_change']:+,.0f})"
                + (f", unmet heat {row['Heat unmet (MWh)']:,.1f} MWh" if row.get("Heat unmet (MWh)", 0) > 0.05 else ""))
    return {"table": pd.DataFrame(rows), "base": base, "step_pct": STEP * 100, "regime": regime}
