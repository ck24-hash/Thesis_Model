"""Run one case with the blocks in elements/: the study of each block that is sized, then the electricity side.

    python system/run_case.py "C:/.../case_2026.json"

The case file is either the system format (system/setup.py) or a battery model case file, read as the same system.
The sized blocks (gas boiler, heat storage, battery) are sized in one of two ways, "system": {"sizing": ...}:

    joint (default, with two sized blocks or more): all together in one optimisation, for the lowest yearly cost of
        the site (system/joint.py), then each block left out once for its value in the system; each block's study
        then runs at its joint size for its own tables (the heat storage's against the system without it);
    sequential (or one sized block): each block's study sizes it with the others fixed, in this order (A16):
        the gas boiler (elements/ng_boiler/study.py), the heat storage (elements/thermal_storage/study.py), the
        battery (elements/battery/study.py).

Then, always: the electricity side (system/electricity.py: supply and demand, self-consumption, the grid bill, without
battery and with the chosen battery) and the site's yearly cost (system/costs.py). A system without a block to size
runs these two only. The results go next to the case file (or to "output_dir"): summary_<tag>.json and
results_<tag>.xlsx. For a battery-only case the battery study's sheets are the same as
elements/battery_reference/run_case.py writes.
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

from elements.battery import study as battery_study  # noqa: E402
from elements.ng_boiler import study as boiler_study  # noqa: E402
from elements.thermal_storage import study as storage_study  # noqa: E402
from system import costs, electricity, joint, setup  # noqa: E402

SIZING_MODES = ("joint", "sequential")


def sizing_mode(case: dict) -> str:
    mode = (case.get("system") or {}).get("sizing") or "joint"
    if mode not in SIZING_MODES:
        raise ValueError(f"Unknown sizing {mode!r}; use one of {', '.join(SIZING_MODES)}.")
    return mode


def run(case: dict, case_dir: Path, tag: str, log=print, sizing: str | None = None) -> tuple[dict, setup.System]:
    """The studies of a case (either format): {"mode", "joint", "boiler", "thermal_storage", "battery": each one's
    results or None, "electricity", "costs"}, and the system they ran. sizing: the case's sizing mode unless given."""
    case = setup.as_system_case(case)
    s = setup.build(case, case_dir)
    blocks = case["blocks"]
    regime = (blocks.get("grid") or {}).get("regime") or {}
    auto, manual = regime.get("auto", True), regime.get("manual")
    plan = joint.plan_of(s, blocks)
    mode = "joint" if (sizing or sizing_mode(case)) == "joint" and len(plan) >= 2 else "sequential"
    out = {"mode": mode, "joint": None, "boiler": None, "thermal_storage": None, "battery": None,
           "electricity": None, "costs": None}
    res_no_battery = None
    if mode == "joint":
        j = out["joint"] = joint.run(s, blocks, regime_auto=auto, regime_manual=manual, log=log)
        sizes = j["sizes"]
        if s.boiler is not None:   # its tables at the joint size, the heat storage in place
            out["boiler"] = boiler_study.run(
                s, regime_auto=auto, regime_manual=manual, log=log,
                sizing_settings={"objective": "custom", "custom_kw": sizes["ng_boiler"], "sizes_kw": [sizes["ng_boiler"]]})
            out["boiler"]["choice"].update(joint=True, storage_kwh=s.storage_kwh or 0.0)
        if sizes.get("thermal_storage"):
            log("\n=== HEAT STORAGE IN THE SYSTEM ===")
            w = j["without"]["thermal_storage"]
            out["thermal_storage"] = storage_study.from_joint(
                s, out["boiler"]["dispatch"], w["heat"], j["value"]["thermal_storage"], w["sizes"].get("ng_boiler"),
                log=log)
        if sizes.get("battery"):
            size = int(sizes["battery"])
            out["battery"] = battery_study.run(
                s, regime_auto=auto, regime_manual=manual, tag=tag, log=log,
                sizing_settings={"objective": "custom", "custom_kwh": size, "sweep_kwh": [size],
                                 "cap_at_subsidy_size": False, "fine_grid_kwh": []})
        else:
            res_no_battery = j["res"]   # no battery: the joint solve's electricity side is exact
    else:
        if s.boiler is not None:
            out["boiler"] = boiler_study.run(s, regime_auto=auto, regime_manual=manual,
                                             sizing_settings=(blocks.get("ng_boiler") or {}).get("sizing"), log=log)
        if s.storage is not None:
            out["thermal_storage"] = storage_study.run(
                s, regime_auto=auto, regime_manual=manual, baseline=out["boiler"]["dispatch"],
                sizing_settings=(blocks.get("thermal_storage") or {}).get("sizing"), log=log)
        if s.battery is not None:
            out["battery"] = battery_study.run(s, regime_auto=auto, regime_manual=manual,
                                               sizing_settings=(blocks.get("battery") or {}).get("sizing"), tag=tag,
                                               log=log)
    out["electricity"] = electricity.run(s, regime_auto=auto, regime_manual=manual, battery=out["battery"],
                                         res_no_battery=res_no_battery, log=log)
    out["costs"] = site_costs(s, out, log)
    return out, s


def site_costs(s: setup.System, out: dict, log=print) -> dict:
    """The site's yearly cost with the sizes chosen: the grid bill of the electricity side (with the battery when
    there is one), the heat side's year (the heat storage's when there is one, else the boiler's)."""
    cases = out["electricity"]["cases"]
    grid = cases["battery" if "battery" in cases else "no_battery"]["kpi"]
    heat = None
    if out["thermal_storage"] is not None:
        heat = out["thermal_storage"]["dispatch"]
    elif out["boiler"] is not None:
        heat = out["boiler"]["dispatch"]
    b = out["battery"]
    sizes = {"ng_boiler": s.boiler_kw, "thermal_storage": s.storage_kwh,
             "battery": b["summary"]["battery_kwh"] if b is not None else None}
    cost = costs.yearly(s, grid, heat, sizes, ems_yr=b["summary"]["battery_ems_yr"] if b is not None else None)
    log("\n=== SITE YEARLY COST ===")
    log(f"  Running {cost['running_total']:,.0f} + investments {cost['investment_total']:,.0f} per year = "
        f"{cost['total']:,.0f} per year")
    return cost


def summary_of(out: dict) -> dict:
    """The run's summary: the battery's (as the reference model writes it) when there is one, with the other
    studies' under their names and the electricity side's under "electricity"."""
    summary = dict(out["battery"]["summary"]) if out["battery"] is not None else {}
    for key in ("boiler", "thermal_storage", "electricity"):
        if out.get(key) is not None:
            summary[key] = out[key]["summary"]
    if out.get("costs") is not None:
        c = out["costs"]
        summary["site"] = {"sizing_mode": out["mode"], "site_yearly_cost": c["total"],
                           "site_running_cost": c["running_total"], "site_investment_per_year": c["investment_total"],
                           **{f"size_{k}": v for k, v in c["sizes"].items()}}
        if out.get("joint") is not None:
            summary["site"].update({f"value_in_system_{k}": v for k, v in out["joint"]["value"].items()})
    return summary


def write_results(out: dict, out_dir: Path, tag: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"summary_{tag}.json", "w", encoding="utf-8") as f:
        json.dump(summary_of(out), f, indent=2, default=float)
    with pd.ExcelWriter(out_dir / f"results_{tag}.xlsx") as xl:
        b = out["battery"]
        if b is not None:
            pd.DataFrame({"Value": b["summary"]}).drop(index="sweep").to_excel(xl, sheet_name="Summary")
            b["sweep"].to_excel(xl, sheet_name="Sizing sweep")
            b["payback"].to_excel(xl, sheet_name="Payback", index=False)
            b["bills"].to_excel(xl, sheet_name="Yearly bills")
            b["monthly_no_battery"].to_excel(xl, sheet_name="Monthly no battery")
            b["monthly_battery"].to_excel(xl, sheet_name="Monthly battery")
            b["dispatch"].to_excel(xl, sheet_name="Dispatch")
        if out.get("costs") is not None:
            costs.table(out["costs"]).to_excel(xl, sheet_name="Site yearly cost", index=False)
        j = out.get("joint")
        if j is not None:
            rows = [{"Block": joint.NAMES[b], "Size": size, "Unit": joint.UNITS[b], "Sized": "fixed" if j["plan"][b] is not None
                     else "jointly", "Site yearly cost without it": j["without"].get(b, {}).get("cost", {}).get("total"),
                     "Value in the system per year": j["value"].get(b)} for b, size in j["sizes"].items()]
            pd.DataFrame(rows).to_excel(xl, sheet_name="Joint sizing", index=False)
        e = out["electricity"]
        pd.DataFrame({c["kpi"]["label"]: c["kpi"] for c in e["cases"].values()}).drop(index=["label", "currency"]).to_excel(
            xl, sheet_name="Electricity")
        for key, c in e["cases"].items():
            suffix = " battery" if key == "battery" else ""
            c["bills"].to_excel(xl, sheet_name=f"Electricity bill{suffix}")
            c["monthly"].to_excel(xl, sheet_name=f"Electricity monthly{suffix}")
        h = out["boiler"]
        if h is not None:
            pd.DataFrame({"Value": h["summary"]}).drop(index="boiler_sweep").to_excel(xl, sheet_name="Boiler summary")
            h["sweep"].to_excel(xl, sheet_name="Boiler sweep")
            h["monthly"].to_excel(xl, sheet_name="Boiler monthly")
            h["dispatch"].to_excel(xl, sheet_name="Boiler dispatch")
        t = out["thermal_storage"]
        if t is not None:
            pd.DataFrame({"Value": t["summary"]}).drop(index="storage_sweep").to_excel(xl, sheet_name="Storage summary")
            t["sweep"].to_excel(xl, sheet_name="Storage sweep")
            t["monthly"].to_excel(xl, sheet_name="Storage monthly")
            t["dispatch"].to_excel(xl, sheet_name="Storage dispatch")


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
    if out["boiler"] is not None:
        h = out["boiler"]["summary"]
        print(f"\n  Boiler {h['boiler_kw']:,.0f} kW: {h['boiler_cost_yr']:,.0f}/yr, lifetime cost "
              f"{h['boiler_lifetime_cost']:,.0f}" + ("" if h["boiler_covers"] else " (does not cover the demand)"))
    if out["thermal_storage"] is not None:
        t = out["thermal_storage"]["summary"]
        print(f"\n  Heat storage {t['storage_kwh']:,.0f} kWh: value {t['storage_value_yr']:,.0f}/yr, "
              f"payback {t['storage_payback_yr']:.1f} yr")
    if out["battery"] is not None:
        sm = out["battery"]["summary"]
        print(f"\n  Battery {sm['battery_kwh']} kWh, regime {sm['regime_battery']}: value {sm['battery_value_yr']:,.0f}/yr, "
              f"payback {sm['battery_payback_yr']:.1f} yr")
    c = out["costs"]
    print(f"\n  Site yearly cost ({out['mode']} sizing): {c['total']:,.0f} (running {c['running_total']:,.0f}, "
          f"investments {c['investment_total']:,.0f} per year)")
    e = out["electricity"]["summary"]
    print(f"\n  Electricity: self-consumption {e['el_sc_pct']:.1f} %, self-sufficiency {e['el_ss_pct']:.1f} %, "
          f"bill {e['el_bill']:,.0f}/yr, export revenue {e['el_export_revenue']:,.0f}/yr")
    print(f"  Written: {out_dir / f'summary_{tag}.json'} and results_{tag}.xlsx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
