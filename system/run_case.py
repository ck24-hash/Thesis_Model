"""Run one case with the blocks in elements/ (today: the battery study).

    python system/run_case.py "C:/.../case_2026.json"

The case file is either the system format (system/setup.py) or a battery model case file, read as the same system.
The results go next to the case file (or to "output_dir"): summary_<tag>.json and results_<tag>.xlsx, with the same
content and layout as elements/battery_reference/run_case.py writes.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the project root

import pandas as pd  # noqa: E402

from elements.battery import study  # noqa: E402
from system import setup  # noqa: E402


def run(case: dict, case_dir: Path, tag: str, log=print) -> tuple[dict, setup.System]:
    """The battery study of a case (either format): its results, and the system it ran."""
    case = setup.as_system_case(case)
    s = setup.build(case, case_dir)
    blocks = case["blocks"]
    regime = (blocks.get("grid") or {}).get("regime") or {}
    out = study.run(s, regime_auto=regime.get("auto", True), regime_manual=regime.get("manual"),
                    sizing_settings=(blocks.get("battery") or {}).get("sizing"), tag=tag, log=log)
    return out, s


def write_results(out: dict, out_dir: Path, tag: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"summary_{tag}.json", "w", encoding="utf-8") as f:
        json.dump(out["summary"], f, indent=2, default=float)
    with pd.ExcelWriter(out_dir / f"results_{tag}.xlsx") as xl:
        pd.DataFrame({"Value": out["summary"]}).drop(index="sweep").to_excel(xl, sheet_name="Summary")
        out["sweep"].to_excel(xl, sheet_name="Sizing sweep")
        out["payback"].to_excel(xl, sheet_name="Payback", index=False)
        out["bills"].to_excel(xl, sheet_name="Yearly bills")
        out["monthly_no_battery"].to_excel(xl, sheet_name="Monthly no battery")
        out["monthly_battery"].to_excel(xl, sheet_name="Monthly battery")
        out["dispatch"].to_excel(xl, sheet_name="Dispatch")


def quiet() -> None:
    warnings.filterwarnings("ignore")
    for name in ("pypsa", "linopy"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run one case with the blocks in elements/.")
    ap.add_argument("case", type=Path, help="the case file (JSON)")
    args = ap.parse_args(argv)
    quiet()
    case_path = args.case.resolve()
    case = setup.load_case(case_path)
    tag = case.get("tag", case_path.stem)
    out, _ = run(case, case_path.parent, tag)
    out_dir = Path(case["output_dir"]) if case.get("output_dir") else case_path.parent
    write_results(out, out_dir, tag)
    sm = out["summary"]
    print(f"\n  {sm['battery_kwh']} kWh, regime {sm['regime_battery']}: value {sm['battery_value_yr']:,.0f}/yr, "
          f"payback {sm['battery_payback_yr']:.1f} yr")
    print(f"  Written: {out_dir / f'summary_{tag}.json'} and results_{tag}.xlsx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
