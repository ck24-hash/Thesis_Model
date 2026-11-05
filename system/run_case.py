"""Run one case with the blocks in elements/: every ticked block sized together, then the year at those sizes, then the
money.

    python system/run_case.py "C:/.../case_2026.json"

The case file is either the system format (system/setup.py) or a battery model case file, read as the same system.
The run, technical results first and the money after:

1. joint sizing (system/joint.py): every sized block (gas boiler, heat pump, heat storage, battery) sized together in
   one optimisation whose objective is the site's yearly cost; a block whose sizing is "custom" keeps its size;
2. each block's year at its size, for its own tab (elements/<block>/study.py: the boiler, the battery, the heat pump;
   the heat storage against the system without it), and the electricity side (system/electricity.py);
3. with and without each technology the system could do without (system/effects.py);
4. the money: the site's yearly cost (system/costs.py);
5. the technical summary (system/technical.py): each size, how it was found and how hard it works, and the year's
   energy flows;
6. sensitivity (system/sensitivity.py): each size -10 % and +10 %, operation only ("system": {"sensitivity": false}
   skips it);
7. battery check (system/battery_check.py): the battery sized again by the reference sweep, against its joint size
   ("system": {"battery_check": false} skips it).

The results go next to the case file (or to "output_dir"): summary_<tag>.json and results_<tag>.xlsx.
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
from elements.heat_pump import study as heat_pump_study  # noqa: E402
from elements.ng_boiler import study as boiler_study  # noqa: E402
from elements.thermal_storage import study as storage_study  # noqa: E402
from system import battery_check, costs, effects, electricity, joint, sensitivity, setup, technical  # noqa: E402


def sensitivity_on(case: dict) -> bool:
    return bool((case.get("system") or {}).get("sensitivity", True))


def run(case: dict, case_dir: Path, tag: str, log=print) -> tuple[dict, setup.System]:
    """The run of a case (either format), in the module's order: {"mode", "joint", "boiler", "heat_pump",
    "thermal_storage", "battery": each one's results or None, "electricity", "effects", "costs", "technical",
    "sensitivity", "battery_check"}, and the system it ran."""
    case = setup.as_system_case(case)
    s = setup.build(case, case_dir)
    blocks = case["blocks"]
    regime = (blocks.get("grid") or {}).get("regime") or {}
    auto, manual = regime.get("auto", True), regime.get("manual")
    out = {"mode": "joint", "joint": None, "boiler": None, "heat_pump": None, "thermal_storage": None, "battery": None,
           "effects": None, "electricity": None, "costs": None, "technical": None, "sensitivity": None,
           "battery_check": None}

    # 1. the sizes, all together
    j = out["joint"] = joint.run(s, blocks, regime_auto=auto, regime_manual=manual, log=log)
    sizes = j["sizes"]

    # 2. each block's year at its size, and the electricity side
    log("\n=== THE YEAR AT THE CHOSEN SIZES ===")
    res_no_battery = None
    if s.boiler is not None and sizes["ng_boiler"]:   # its tables at the joint size (none at 0), storage in place
        out["boiler"] = boiler_study.run(s, sizes["ng_boiler"], j["regime"], log=log)
        out["boiler"]["choice"].update(joint=True, storage_kwh=s.storage_kwh or 0.0, heat_pump_kw=s.heat_pump_kw)
    if sizes.get("battery"):
        size = int(sizes["battery"])
        out["battery"] = battery_study.run(
            s, regime_auto=auto, regime_manual=manual, tag=tag, log=log,
            sizing_settings={"objective": "custom", "custom_kwh": size, "sweep_kwh": [size],
                             "cap_at_subsidy_size": False, "fine_grid_kwh": []})
    else:
        res_no_battery = j["res"]   # no battery: the joint solve's electricity side is exact
    out["electricity"] = electricity.run(s, regime_auto=auto, regime_manual=manual, battery=out["battery"],
                                         res_no_battery=res_no_battery,
                                         regime=j["regime"] if res_no_battery is not None else None, log=log)

    # 3. with and without each technology
    out["effects"] = effects.run(s, case, case_dir, out, regime_auto=auto, regime_manual=manual, log=log)
    e = out["effects"].get("thermal_storage") or {}
    if sizes.get("thermal_storage") and e.get("evaluated"):   # its tab: against the best system without it
        log("\n=== HEAT STORAGE IN THE SYSTEM ===")
        out["thermal_storage"] = storage_study.from_joint(
            s, out["boiler"]["dispatch"] if out["boiler"] is not None else j["heat"], e["heat_without"],
            e["difference"], e["sizes_without"].get("ng_boiler"), log=log, effect=e)

    # 4. the money
    out["costs"] = site_costs(s, out, log)
    if s.heat_pump is not None:
        cases = out["electricity"]["cases"]
        regime_used = cases["battery" if "battery" in cases else "no_battery"]["kpi"]["regime"]
        out["heat_pump"] = heat_pump_study.run(s, out["heat_side"], regime_used,
                                               fixed=(j["plan"].get("heat_pump") is not None), log=log)

    # 5. the technical summary, from the run's year
    res = out["battery"]["dispatch"] if out["battery"] is not None else j["res"]
    out["technical"] = {"equipment": technical.equipment(s, res, out["heat_side"], sizes, j["plan"]),
                        "energy": technical.energy(s, res, out["heat_side"])}

    # 6. sensitivity, 7. battery check
    if sensitivity_on(case):
        out["sensitivity"] = sensitivity.run(s, case, case_dir, j, log=log)
    if s.battery is not None and j["plan"].get("battery") is None and battery_check.enabled(case):
        out["battery_check"] = battery_check.run(s, case, out, regime_auto=auto, regime_manual=manual, tag=tag, log=log)
    return out, s


def site_costs(s: setup.System, out: dict, log=print) -> dict:
    """The site's yearly cost with the sizes chosen: the grid bill of the electricity side (with the battery when
    there is one), the heat side's year (the heat storage's when there is one, else the boiler's, else the joint
    sizing's). With a heat pump the heat side depends on the electricity side, so it is the same year's: the battery
    study's, else the joint sizing's."""
    cases = out["electricity"]["cases"]
    grid = cases["battery" if "battery" in cases else "no_battery"]["kpi"]
    heat = None
    if s.heat_pump is not None:
        b = out["battery"]
        heat = b["heat_dispatch"] if b is not None and b.get("heat_dispatch") is not None else out["joint"]["heat"]
    elif out["thermal_storage"] is not None:
        heat = out["thermal_storage"]["dispatch"]
    elif out["boiler"] is not None:
        heat = out["boiler"]["dispatch"]
    else:   # no boiler study (none, or given no size); bought CO2 only
        heat = out["joint"]["heat"]
    out["heat_side"] = heat
    b = out["battery"]
    sizes = {"ng_boiler": s.boiler_kw, "heat_pump": s.heat_pump_kw, "thermal_storage": s.storage_kwh,
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
    for key in ("boiler", "heat_pump", "thermal_storage", "electricity"):
        if out.get(key) is not None:
            summary[key] = out[key]["summary"]
    if out.get("costs") is not None:
        c = out["costs"]
        summary["site"] = {"site_yearly_cost": c["total"],
                           "site_running_cost": c["running_total"], "site_investment_per_year": c["investment_total"],
                           **{f"size_{k}": v for k, v in c["sizes"].items()}}
    if out.get("effects"):
        summary["effects"] = {}
        for x, e in out["effects"].items():
            if e.get("evaluated"):
                summary["effects"].update({f"{x}_lowers_yearly_cost_by": e["difference"],
                                           f"{x}_extra_investment": e["extra_investment"],
                                           f"{x}_running_saving": e["running_saving"], f"{x}_payback_yr": e["payback_yr"]})
    if out.get("battery_check") is not None:
        bc = out["battery_check"]
        summary["battery_check"] = {"joint_kwh": bc["joint"]["size"], "sweep_kwh": bc["sweep"]["size"], "same": bc["same"]}
    return summary


def write_results(out: dict, out_dir: Path, tag: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"summary_{tag}.json", "w", encoding="utf-8") as f:
        json.dump(summary_of(out), f, indent=2, default=float)
    with pd.ExcelWriter(out_dir / f"results_{tag}.xlsx") as xl:
        b = out["battery"]
        if b is not None:
            pd.DataFrame({"Value": b["summary"]}).drop(index="sweep").to_excel(xl, sheet_name="Summary")
            b["payback"].to_excel(xl, sheet_name="Payback", index=False)
            b["bills"].to_excel(xl, sheet_name="Yearly bills")
            b["monthly_no_battery"].to_excel(xl, sheet_name="Monthly no battery")
            b["monthly_battery"].to_excel(xl, sheet_name="Monthly battery")
            b["dispatch"].to_excel(xl, sheet_name="Dispatch")
        if out.get("technical") is not None:
            pd.DataFrame(out["technical"]["equipment"]).to_excel(xl, sheet_name="Equipment", index=False)
            pd.DataFrame(out["technical"]["energy"]).to_excel(xl, sheet_name="Energy over the year", index=False)
        if out.get("costs") is not None:
            costs.table(out["costs"]).to_excel(xl, sheet_name="Site yearly cost", index=False)
        if out.get("sensitivity") is not None:
            out["sensitivity"]["table"].to_excel(xl, sheet_name="Sensitivity", index=False)
        if out.get("battery_check") is not None:
            bc = out["battery_check"]
            pd.DataFrame({"Joint sizing": bc["joint"], "Reference sweep": bc["sweep"]}).to_excel(xl, sheet_name="Battery check")
            bc["table"].to_excel(xl, sheet_name="Battery check", startrow=12, index=False)
        j = out.get("joint")
        if j is not None:
            rows = [{"Block": joint.NAMES[b], "Size": size, "Unit": joint.UNITS[b],
                     "Sized": "fixed" if j["plan"][b] is not None else "jointly"} for b, size in j["sizes"].items()]
            pd.DataFrame(rows).to_excel(xl, sheet_name="Joint sizing", index=False)
        if out.get("effects"):
            rows = [{"Technology": e["name"], "Evaluated": e.get("evaluated"), "Why not": e.get("reason"),
                     "Lowers the yearly cost by": e.get("difference"), "Extra investment": e.get("extra_investment"),
                     "Running saving per year": e.get("running_saving"), "Payback (yr)": e.get("payback_yr")}
                    for e in out["effects"].values()]
            pd.DataFrame(rows).to_excel(xl, sheet_name="With and without", index=False)
            for x, e in out["effects"].items():
                if e.get("evaluated"):
                    sheet = f"Without {x}"[:31]
                    e["costs"].to_excel(xl, sheet_name=sheet, index=False)
                    e["figures"].to_excel(xl, sheet_name=sheet, index=False, startrow=len(e["costs"]) + 2)
        e = out["electricity"]
        pd.DataFrame({c["kpi"]["label"]: c["kpi"] for c in e["cases"].values()}).drop(index=["label", "currency"]).to_excel(
            xl, sheet_name="Electricity")
        for key, c in e["cases"].items():
            suffix = " battery" if key == "battery" else ""
            c["bills"].to_excel(xl, sheet_name=f"Electricity bill{suffix}")
            c["monthly"].to_excel(xl, sheet_name=f"Electricity monthly{suffix}")
        h = out["boiler"]
        if h is not None:
            pd.DataFrame({"Value": h["summary"]}).to_excel(xl, sheet_name="Boiler summary")
            h["monthly"].to_excel(xl, sheet_name="Boiler monthly")
            h["dispatch"].to_excel(xl, sheet_name="Boiler dispatch")
        hp = out.get("heat_pump")
        if hp is not None:
            pd.DataFrame({"Value": hp["summary"]}).to_excel(xl, sheet_name="Heat pump summary")
            hp["monthly"].to_excel(xl, sheet_name="Heat pump monthly")
            d = hp["dispatch"]
            d.assign(cop=hp["cop"].reindex(d.index)).to_excel(xl, sheet_name="Heat pump dispatch")
        t = out["thermal_storage"]
        if t is not None:
            pd.DataFrame({"Value": t["summary"]}).to_excel(xl, sheet_name="Storage summary")
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
    if out["heat_pump"] is not None:
        hp = out["heat_pump"]["summary"]
        print(f"\n  Heat pump {hp['heat_pump_kw']:,.0f} kW: {hp['hp_heat_mwh']:,.0f} MWh of heat, "
              f"{hp['hp_electricity_mwh']:,.0f} MWh of electricity, SPF {hp['spf'] or 0:.2f}")
    if out["thermal_storage"] is not None:
        t = out["thermal_storage"]["summary"]
        print(f"\n  Heat storage {t['storage_kwh']:,.0f} kWh: value {t['storage_value_yr']:,.0f}/yr, "
              f"payback {t['storage_payback_yr']:.1f} yr")
    if out["battery"] is not None:
        sm = out["battery"]["summary"]
        print(f"\n  Battery {sm['battery_kwh']} kWh, regime {sm['regime_battery']}: value {sm['battery_value_yr']:,.0f}/yr, "
              f"payback {sm['battery_payback_yr']:.1f} yr")
    if out["battery_check"] is not None:
        bc = out["battery_check"]
        print(f"\n  Battery check: joint sizing {bc['joint']['size']:,.0f} kWh, reference sweep {bc['sweep']['size']:,.0f} kWh")
    c = out["costs"]
    print(f"\n  Site yearly cost: {c['total']:,.0f} (running {c['running_total']:,.0f}, "
          f"investments {c['investment_total']:,.0f} per year)")
    e = out["electricity"]["summary"]
    print(f"\n  Electricity: self-consumption {e['el_sc_pct']:.1f} %, self-sufficiency {e['el_ss_pct']:.1f} %, "
          f"bill {e['el_bill']:,.0f}/yr, export revenue {e['el_export_revenue']:,.0f}/yr")
    print(f"  Written: {out_dir / f'summary_{tag}.json'} and results_{tag}.xlsx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
