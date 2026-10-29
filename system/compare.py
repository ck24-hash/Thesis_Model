"""Run case files with the reference model (elements/battery_reference) and with the blocks (system/), and compare
the summary and every result table.

    python system/compare.py examples/battery/case_example_CH.json examples/blocks/case_blocks_CH.json [more]

A case is either a reference case file (one workbook) or a system case file (one input file per block); for the
latter the reference model gets the blocks' inputs as one workbook in its own format (system/setup.py
reference_frame). Nothing is written. A summary value or a table cell that differs is listed with both values;
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

import parameters  # noqa: E402  (the reference's parameters.py)
import run_case as reference  # noqa: E402  (elements/battery_reference/run_case.py)
from engine import inputs, pipeline  # noqa: E402  (the reference's engine)
from engine.setup import Setup  # noqa: E402

from system import run_case as blocks  # noqa: E402
from system import setup  # noqa: E402

TABLES = ("sweep", "payback", "bills", "monthly_no_battery", "monthly_battery", "dispatch")


def reference_setup(case: dict, case_dir: Path, read=None) -> tuple[Setup, dict]:
    """The reference model's Setup for a case of either format, and the case in the reference format. read(path)
    gives an input file's first sheet (default: read each file once)."""
    if "blocks" not in case:
        return reference.setup_from_case(case, case_dir), case
    sc = setup.with_paths(case, case_dir)
    ref = setup.to_battery_case(sc)
    m = setup.market_of(sc)
    params = parameters.load(m["country"], m["region"], m["utility"], m["year"],
                             business_model=ref["business_model"], overrides=ref.get("overrides"))
    study = inputs.from_frame(setup.reference_frame(sc, read or setup.excel_reader()), year=ref["year"],
                              modules=ref["pv_modules"], use_existing_pv=ref["use_existing_pv"],
                              eur_to_local=params["tariff"].get("eur_to_local", 1.0))
    return Setup(study, params, grid=ref.get("grid")), ref


def run_reference(case: dict, case_dir: Path, tag: str) -> dict:
    s, ref = reference_setup(case, case_dir)
    regime = ref.get("regime", {})
    return pipeline.run(s, regime_auto=regime.get("auto", True), regime_manual=regime.get("manual"),
                        sizing_settings=ref.get("sizing"), tag=tag, log=lambda *a, **k: None)


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
    ap.add_argument("cases", type=Path, nargs="+", help="case files (JSON), either format")
    args = ap.parse_args(argv)
    blocks.quiet()
    failed = 0
    for path in args.cases:
        path = path.resolve()
        case = json.loads(path.read_text(encoding="utf-8"))
        tag = case.get("tag", path.stem)
        ref = run_reference(case, path.parent, tag)
        new = blocks.run(case, path.parent, tag, log=lambda *a, **k: None, sizing="sequential")[0]["battery"]
        diffs = differences(ref, new)
        failed += bool(diffs)
        print(f"{path.name}: {'identical' if not diffs else f'{len(diffs)} differences'}", flush=True)
        for line in diffs:
            print("   ", line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
