"""What the two battery study run types share on the page: the column roles of the time stamps, the progress stages
read from the log, and the results the page draws. Both models write the same log lines and the same tables."""
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
# progress: a log line containing the marker moves the run to that stage
STAGES = [("Reading", 1), ("Auto DUP", 1), ("Regime ", 1), ("Solving the year without battery", 2),
          ("BATTERY SIZING SWEEP", 3), ("Chosen:", 4), ("Writing", 6)]
STAGE_LABELS = [
    (1, "Read the inputs, find the starting regime", False),
    (2, "Optimise the year without battery: the baseline bill", False),
    (3, "Size sweep: optimise the year for each size", True),
    (4, "Optimise the chosen size; its bill, value, PV saving and payback scenarios", False),
    (6, "Write summary_<tag>.json and results_<tag>.xlsx", False),
]
VIEW = "battery_study"   # the results panel of the page


def track(run, text: str) -> None:
    """Moves the run's stage and counts the sizes solved, from one log line."""
    for marker, stage in STAGES:
        if marker in text:
            run.stage = max(run.stage, stage)
    if " kWh ..." in text:
        run.done += 1
    if text.startswith("Stage 1"):
        run.total = text.count(",") + 1


def first_stage(cfg: dict, cap_at_subsidy: bool, threshold_kwh: float) -> tuple[list, int | None]:
    """The sizes the sweep solves first, and the subsidy cap (the rule of the sweep in both models)."""
    coarse = sorted(set(cfg["sweep_kwh"]) | ({cfg["custom_kwh"]} if cfg["objective"] == "custom" else set()))
    cap = None
    if cfg["cap_at_subsidy_size"] and cap_at_subsidy:
        cap = round(threshold_kwh)
        coarse = sorted({size for size in coarse if size <= cap} | {cap})
    return coarse, cap


def results_for_page(out: dict, dt: float, choice: dict, run_type: str) -> dict:
    d = out["dispatch"]
    hourly = d.resample("h").mean()
    energy = pd.DataFrame({"load": d["load"], "pv": d["pv"], "grid_import": d["grid_import"],
                           "grid_export": d["grid_export"], "charged": (-d["battery_power"]).clip(lower=0),
                           "discharged": d["battery_power"].clip(lower=0)}) * dt
    daily = energy.resample("D").sum()
    soc_max = d["battery_soc"].resample("D").max()
    return clean({
        "run_type": run_type,
        "view": VIEW,
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
    })
