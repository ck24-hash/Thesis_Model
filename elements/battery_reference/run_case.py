"""Run one battery study from a case file.

    python models/battery/run_case.py "C:/.../case_2026.json"

The case file holds only what is specific to the study (which input file, which market, how many modules) and
stays next to the grower's data, never in this repo. Everything else comes from params/. The results are written
next to the case file (or to "output_dir"): summary_<tag>.json and results_<tag>.xlsx.

Case file keys (only input_file and market are required):
    input_file        the input workbook, relative to the case file or absolute
    year              the calendar year of the input (default: market.year)
    columns           other column names than engine/inputs.py DEFAULT_COLUMNS
    market            {"country": "CH", "region": "GE", "utility": "SIG", "year": 2026}; "canton" works as
                      "region". NL: {"country": "NL", "region": "WestlandInfra", "utility": "MS", "year": 2026};
                      FR: {"country": "FR", "region": "HTA", "utility": "Reference", "year": 2025}
    business_model    "direct_sales" (default) or "eaas"
    pv_modules        Voltiris modules (default 0)
    use_existing_pv   true when the input has the existing PV column (default false)
    grid              {"import_max_kw": 750, "export_max_kw": 750}; null or missing = automatic
    regime            {"auto": true} or {"auto": false, "manual": "B"} (FR: "LU" by default, or "CU")
    sizing            objective (profit, payback, custom), custom_kwh, sweep_kwh, fine_grid_kwh,
                      fine_window_kwh, cap_at_subsidy_size (see engine/sizing.py DEFAULTS)
    overrides         single values per block for this study only, in the market's currency, e.g.
                      {"tariff": {"export": {"per_kwh": 0.066}}} or {"ems": {"savings_fee_pct": {"voltiris": 0.1}}}
    tag               used in the output file names (default: the case file's name)
    output_dir        where the results go (default: the case file's folder)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402

import parameters  # noqa: E402
from engine import inputs, pipeline  # noqa: E402
from engine.setup import Setup  # noqa: E402


def load_case(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        case = json.load(f)
    for key in ("input_file", "market"):
        if key not in case:
            raise KeyError(f"The case file has no '{key}'.")
    return case


def setup_from_case(case: dict, case_dir: Path) -> Setup:
    m = case["market"]
    region = m.get("region", m.get("canton"))
    params = parameters.load(m["country"], region, m["utility"], m["year"],
                             business_model=case.get("business_model", "direct_sales"),
                             overrides=case.get("overrides"))
    input_path = Path(case["input_file"])
    if not input_path.is_absolute():
        input_path = case_dir / input_path
    study = inputs.read_excel(input_path, year=case.get("year", m["year"]), modules=case.get("pv_modules", 0),
                              use_existing_pv=case.get("use_existing_pv", False),
                              eur_to_local=params["tariff"].get("eur_to_local", 1.0),
                              columns=case.get("columns"))
    return Setup(study, params, grid=case.get("grid"))


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run one battery study from a case file.")
    ap.add_argument("case", type=Path, help="the case file (JSON)")
    args = ap.parse_args(argv)
    warnings.filterwarnings("ignore")
    for name in ("pypsa", "linopy"):
        logging.getLogger(name).setLevel(logging.WARNING)
    case_path = args.case.resolve()
    case = load_case(case_path)
    tag = case.get("tag", case_path.stem)
    s = setup_from_case(case, case_path.parent)
    regime = case.get("regime", {})
    out = pipeline.run(s, regime_auto=regime.get("auto", True), regime_manual=regime.get("manual"),
                       sizing_settings=case.get("sizing"), tag=tag)
    out_dir = Path(case["output_dir"]) if case.get("output_dir") else case_path.parent
    write_results(out, out_dir, tag)
    sm = out["summary"]
    print(f"\n  {sm['battery_kwh']} kWh, regime {sm['regime_battery']}: value {sm['battery_value_yr']:,.0f}/yr, "
          f"payback {sm['battery_payback_yr']:.1f} yr")
    print(f"  Written: {out_dir / f'summary_{tag}.json'} and results_{tag}.xlsx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
