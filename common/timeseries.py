"""Time series shared by every block and the interface: build the time stamps, detect the time step, and bring a
coarser curve (hourly, 30 min) to the model's 15-minute step.

How each column is converted depends on its kind, which the caller gives from the column mapping:
    power   kW, W, W per module: an average over the step, so the value is repeated in each quarter hour
    price   EUR/kWh, CHF/kWh: repeated
    state   a level (temperature, CO2 setpoint): repeated
    energy  kWh or MWh per step: divided by the number of quarter hours in the step
A column without a kind is not converted: the conversion stops with an error instead of guessing.

Assumption T1: a time stamp marks the start of its step (hour 13 covers 13:00 to 14:00). Data stamped at the end of
the step (hours 1 to 24) is refused by the time stamp check, since hour 24 does not exist.

    python common/timeseries.py input.xlsx --year 2026 --kind "Loadcurve (kW)=power" --kind "Day ahead kWh=price"
writes input_15min.xlsx next to the input (or to -o).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_STEP_MIN = 15
KINDS = {"power": "repeat", "price": "repeat", "state": "repeat", "energy": "divide"}
TIME_COLUMNS = {"month": "Month", "day": "Day", "hour": "Hour", "minute": "Minute"}


def timestamps(df: pd.DataFrame, year: int, names: dict | None = None) -> pd.DatetimeIndex:
    """Time stamps from the Month, Day, Hour (and Minute, 0 when the column is missing) columns and the year."""
    n = {**TIME_COLUMNS, **(names or {})}
    minute = df[n["minute"]] if n.get("minute") in df.columns else 0
    return pd.DatetimeIndex(pd.to_datetime(dict(year=year, month=df[n["month"]], day=df[n["day"]],
                                                hour=df[n["hour"]], minute=minute)))


def step_info(index: pd.DatetimeIndex) -> dict:
    """The most common step in minutes, and how many steps differ from it (gaps, repeated or missing hours)."""
    if len(index) < 2:
        raise ValueError("At least two time stamps are needed to find the time step.")
    diffs = pd.Series((index[1:] - index[:-1]).total_seconds() / 60)
    step = float(diffs.mode().iloc[0])
    return {"step_minutes": step, "irregular_steps": int((diffs != step).sum()), "rows": len(index)}


def factor_to_model_step(step_minutes: float) -> int:
    """How many quarter hours one step holds. Steps shorter than 15 min, or not a whole number of quarter hours, are
    refused: they would need averaging, which is not done here."""
    k = step_minutes / MODEL_STEP_MIN
    if step_minutes < MODEL_STEP_MIN or abs(k - round(k)) > 1e-9:
        raise ValueError(f"A {step_minutes:g}-minute step cannot be brought to {MODEL_STEP_MIN} min: "
                         f"only whole multiples of {MODEL_STEP_MIN} min are converted.")
    return int(round(k))


def to_model_step(values: pd.DataFrame, index: pd.DatetimeIndex, kinds: dict[str, str]) -> pd.DataFrame:
    """The columns named in kinds at 15 minutes, on a new 15-minute index. values is aligned row by row with index."""
    missing = [c for c in values.columns if c not in kinds]
    unknown = {c: k for c, k in kinds.items() if k not in KINDS}
    if missing:
        raise ValueError(f"No kind given for {missing}: say if each column is power, price, state or energy.")
    if unknown:
        raise ValueError(f"Unknown kind {unknown}; use one of {list(KINDS)}.")
    k = factor_to_model_step(step_info(index)["step_minutes"])
    offsets = pd.to_timedelta(np.tile(np.arange(k) * MODEL_STEP_MIN, len(index)), unit="min")
    new_index = pd.DatetimeIndex(index.repeat(k) + offsets)
    out = pd.DataFrame(np.repeat(values.to_numpy(dtype=float), k, axis=0), index=new_index, columns=values.columns)
    for col, kind in kinds.items():
        if KINDS[kind] == "divide":
            out[col] = out[col] / k
    return out


def with_time_columns(frame: pd.DataFrame, names: dict | None = None) -> pd.DataFrame:
    """The frame with Month, Day, Hour, Minute columns in front (the input workbook format) and a plain index."""
    n = {**TIME_COLUMNS, **(names or {})}
    i = frame.index
    time = pd.DataFrame({n["month"]: i.month, n["day"]: i.day, n["hour"]: i.hour, n["minute"]: i.minute})
    return pd.concat([time, frame.reset_index(drop=True)], axis=1)


def convert_file(src: Path, dst: Path, year: int, kinds: dict[str, str], names: dict | None = None) -> dict:
    """Read a workbook (first sheet), check its step and write it at 15 minutes with only the time columns and the
    columns in kinds. Returns the step found and what was done."""
    df = pd.read_excel(src)
    df = df.dropna(subset=[c for key, c in {**TIME_COLUMNS, **(names or {})}.items()
                           if key != "minute" and c in df.columns])
    index = timestamps(df, year, names)
    info = step_info(index)
    out = with_time_columns(to_model_step(df[list(kinds)].reset_index(drop=True), index, kinds), names)
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.to_excel(dst, index=False)
    return {**info, "rows_out": len(out), "written": str(dst)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bring a workbook's curves to 15-minute steps.")
    ap.add_argument("input", type=Path)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--kind", action="append", default=[], metavar="COLUMN=KIND",
                    help=f"one per column to keep; KIND is one of {', '.join(KINDS)}")
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args(argv)
    kinds = dict(item.rsplit("=", 1) for item in args.kind)
    if not kinds:
        ap.error("give at least one --kind COLUMN=KIND")
    dst = args.output or args.input.with_name(f"{args.input.stem}_15min.xlsx")
    r = convert_file(args.input, dst, args.year, kinds)
    print(f"Step found: {r['step_minutes']:g} min ({r['irregular_steps']} irregular steps), {r['rows']} rows "
          f"-> {r['rows_out']} rows at {MODEL_STEP_MIN} min\nWritten: {r['written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
