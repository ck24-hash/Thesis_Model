"""What the run types share on the page: the column roles of the time stamps, the reference run type's progress
stages, and the results the page draws, each in its own part: the electricity side (every run), the battery study,
the gas boiler study and the heat storage study."""
from __future__ import annotations

import pandas as pd

from interface.tables import clean, rounded

# role, what it is, unit, kind (how common/timeseries.py brings it to 15 min), when it is needed, block
TIME_ROLES = [
    ("month", "month of the row", "1-12", "time", "always", "time"),
    ("day", "day of the month", "1-31", "time", "always", "time"),
    ("hour", "hour of the day", "0-23", "time", "always", "time"),
    ("minute", "minute of the hour", "0, 15, 30, 45", "time", "15-min data; 0 when missing", "time"),
]
# the reference model's progress: a log line containing the marker moves the run to that stage
STAGES = [("Reading", 1), ("Auto DUP", 1), ("Regime ", 1), ("Solving the year without battery", 2),
          ("BATTERY SIZING SWEEP", 3), ("Chosen:", 4), ("=== ELECTRICITY", 5), ("=== SITE YEARLY COST", 5),
          ("Writing", 6)]
STAGE_LABELS = [   # stage, label, counts the sizes solved, the block it belongs to
    (1, "Read the inputs, find the starting regime", False, None),
    (2, "Optimise the year without battery: the baseline bill", False, "battery"),
    (3, "Size sweep: optimise the year for each size", True, "battery"),
    (4, "Optimise the chosen size; its bill, value, PV saving and payback scenarios", False, "battery"),
    (5, "Electricity side and the site's yearly cost", False, None),
    (6, "Write summary_<tag>.json and results_<tag>.xlsx", False, None),
]


def track(run, text: str) -> None:
    """Moves the run's stage and counts the battery sizes solved, from one log line."""
    for marker, stage in STAGES:
        if marker in text:
            run.stage = max(run.stage, stage)
    if " kWh ..." in text:
        run.done["battery"] = run.done.get("battery", 0) + 1


def first_stage(cfg: dict, cap_at_subsidy: bool, threshold_kwh: float) -> tuple[list, int | None]:
    """The battery sizes the sweep solves first, and the subsidy cap (the rule of the sweep in both models)."""
    coarse = sorted(set(cfg["sweep_kwh"]) | ({cfg["custom_kwh"]} if cfg["objective"] == "custom" else set()))
    cap = None
    if cfg["cap_at_subsidy_size"] and cap_at_subsidy:
        cap = round(threshold_kwh)
        coarse = sorted({size for size in coarse if size <= cap} | {cap})
    return coarse, cap


def battery_page(out: dict, dt: float, choice: dict) -> dict:
    """The battery study's results for the page."""
    d = out["dispatch"]
    hourly = d.resample("h").mean()
    energy = pd.DataFrame({"load": d["load"], "pv": d["pv"], "grid_import": d["grid_import"],
                           "grid_export": d["grid_export"], "charged": (-d["battery_power"]).clip(lower=0),
                           "discharged": d["battery_power"].clip(lower=0)}) * dt
    daily = energy.resample("D").sum()
    soc_max = d["battery_soc"].resample("D").max()
    return {
        "choice": choice,
        "daily": {"start": daily.index[0].isoformat(), **{c: rounded(daily[c], 1) for c in daily.columns},
                  "soc_max": rounded(soc_max, 1)},
        "summary": out["summary"],
        "sweep": out["sweep"].reset_index(),
        "bills": out["bills"],
        "monthly_no_battery": out["monthly_no_battery"],
        "monthly_battery": out["monthly_battery"],
        "payback": out["payback"],
        "baseline": out["baseline"],
        "dispatch": {"start": hourly.index[0].isoformat(), **{c: rounded(hourly[c], 3) for c in hourly.columns}},
    }


def boiler_page(out: dict, dt: float) -> dict:
    """The gas boiler study's results for the page: heat in MWh per day, CO2 in t per day."""
    d = out["dispatch"]
    daily = (d[["heat_demand", "boiler_heat", "heat_release", "heat_unmet", "gas",
                "co2_demand", "co2_supplied", "co2_vented"]] * dt / 1000).resample("D").sum()
    return {
        "choice": out["choice"],
        "summary": out["summary"],
        "sweep": out["sweep"].reset_index(),
        "monthly": out["monthly"],
        "daily": {"start": daily.index[0].isoformat(), **{c: rounded(daily[c], 3) for c in daily.columns}},
    }


def electricity_page(e: dict) -> dict:
    """The electricity side for the page: per case (without battery, with battery) its key figures, bills, month by
    month table and the hourly split (kW) for the week chart."""
    out = {}
    for key, c in e["cases"].items():
        hourly = c["split"][["load", "voltiris_to_load", "existing_to_load", "battery_to_load", "grid_to_load",
                             "pv_to_battery", "pv_exported", "battery_to_grid", "grid_to_battery", "pv",
                             "battery_soc"]].resample("h").mean()
        out[key] = {"kpi": c["kpi"], "bills": c["bills"], "monthly": c["monthly"],
                    "hourly": {"start": hourly.index[0].isoformat(), **{k: rounded(hourly[k], 2) for k in hourly}}}
    return {"cases": out}


def storage_page(out: dict, dt: float) -> dict:
    """The heat storage study's results for the page: heat in MWh per day, the highest heat stored per day."""
    d, b = out["dispatch"], out["baseline"]
    daily = (d[["storage_charge", "storage_discharge", "heat_release"]] * dt / 1000).resample("D").sum()
    daily["heat_release_no_storage"] = (b["heat_release"] * dt / 1000).resample("D").sum()
    daily["soc_max"] = d["storage_soc"].resample("D").max() / 1000
    hourly = d[["heat_demand", "boiler_heat", "storage_charge", "storage_discharge", "heat_release", "heat_unmet",
                "storage_soc", "gas"]].resample("h").mean()
    hourly["boiler_heat_no_storage"] = b["boiler_heat"].resample("h").mean()
    return {
        "choice": out["choice"],
        "summary": out["summary"],
        "sweep": out["sweep"].reset_index(),
        "monthly": out["monthly"],
        "value_parts": out.get("value_parts", {}),
        "daily": {"start": daily.index[0].isoformat(), **{c: rounded(daily[c], 3) for c in daily.columns}},
        "hourly": {"start": hourly.index[0].isoformat(), **{c: rounded(hourly[c], 2) for c in hourly.columns}},
    }


def system_page(mode: str, cost: dict, j: dict | None = None) -> dict:
    """The site's yearly cost, and with the joint sizing the sizes found and each block's value in the system."""
    page = {"mode": mode, "costs": cost}
    if j is not None:
        page["joint"] = {"sizes": j["sizes"], "plan": j["plan"], "value": j["value"], "notes": j["notes"],
                         "without": {b: {"sizes": w["sizes"], "total": w["cost"]["total"]} for b, w in j["without"].items()},
                         "total": j["cost"]["total"], "regime": j["regime"], "battery_max_kwh": j["battery_max_kwh"]}
    return page


def compare_page(c: dict) -> dict:
    """Scenario A against scenario B: the yearly cost line by line, the sizes and key figures, and B's own yearly
    cost."""
    keys = ("without", "also", "names", "costs", "figures", "total_a", "total_b", "difference", "invested_a",
            "invested_b", "extra_investment", "running_saving", "payback_yr")
    return {**{k: c[k] for k in keys}, "b_mode": c["b"]["mode"], "b_costs": c["b"]["costs"]}


def results_for_page(run_type: str, battery: dict | None = None, boiler: dict | None = None,
                     summary: dict | None = None, electricity: dict | None = None,
                     storage: dict | None = None, system: dict | None = None, compare: dict | None = None) -> dict:
    """Every study's results, and every summary value in one flat list (for the Files tab)."""
    flat = {}
    for key, value in (summary or {}).items():
        if isinstance(value, dict):
            flat.update({k: v for k, v in value.items() if not isinstance(v, (list, dict))})
        elif not isinstance(value, list):
            flat[key] = value
    return clean({"run_type": run_type, "view": "system", "system": system, "compare": compare,
                  "electricity": electricity, "battery": battery, "boiler": boiler, "storage": storage,
                  "summary": flat})
