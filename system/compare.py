"""Run battery model case files with the reference model (elements/battery_reference) and with the blocks (system/),
and compare the summary and every result table.

    python system/compare.py examples/battery/case_example_CH.json [more case files]

Nothing is written next to the case files. A summary value or a table cell that differs is listed with both values;
"identical" means equal to the last digit. Exit code 0 when every case is identical.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "elements" / "battery_reference"))

import pandas as pd  # noqa: E402

import run_case as reference  # noqa: E402  (elements/battery_reference/run_case.py)
from engine import pipeline  # noqa: E402  (the reference's engine)
from system import run_case as blocks  # noqa: E402

TABLES = ("sweep", "payback", "bills", "monthly_no_battery", "monthly_battery", "dispatch")


def run_reference(case: dict, case_dir: Path, tag: str) -> dict:
    s = reference.setup_from_case(case, case_dir)
    regime = case.get("regime", {})
    return pipeline.run(s, regime_auto=regime.get("auto", True), regime_manual=regime.get("manual"),
                        sizing_settings=case.get("sizing"), tag=tag, log=lambda *a, **k: None)


def same(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


def differences(ref: dict, new: dict, limit: int = 10) -> list[str]:
    out = []
    for key in sorted(set(ref["summary"]) | set(new["summary"])):
        a, b = ref["summary"].get(key, "<missing>"), new["summary"].get(key, "<missing>")
        if key == "sweep":
            a, b = json.dumps(a, default=str), json.dumps(b, default=str)
        if not same(a, b):
            out.append(f"summary {key}: reference {a!r}, blocks {b!r}")
    for name in TABLES:
        a, b = ref[name], new[name]
        if list(a.columns) != list(b.columns) or not a.index.equals(b.index):
            out.append(f"{name}: columns or rows differ ({list(a.columns)} vs {list(b.columns)})")
            continue
        diff = ~((a == b) | (a.isna() & b.isna()))
        for row, col in list(zip(*diff.to_numpy().nonzero()))[:limit]:
            out.append(f"{name} [{a.index[row]}, {a.columns[col]}]: reference {a.iat[row, col]!r}, "
                       f"blocks {b.iat[row, col]!r}")
        if diff.to_numpy().sum() > limit:
            out.append(f"{name}: {int(diff.to_numpy().sum())} cells differ in all")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare the blocks with the reference battery model.")
    ap.add_argument("cases", type=Path, nargs="+", help="battery model case files (JSON)")
    args = ap.parse_args(argv)
    blocks.quiet()
    failed = 0
    for path in args.cases:
        path = path.resolve()
        case = reference.load_case(path)
        tag = case.get("tag", path.stem)
        ref = run_reference(case, path.parent, tag)
        new, _ = blocks.run(case, path.parent, tag, log=lambda *a, **k: None)
        diffs = differences(ref, new)
        failed += bool(diffs)
        print(f"{path.name}: {'identical' if not diffs else f'{len(diffs)} differences'}", flush=True)
        for line in diffs:
            print("   ", line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
