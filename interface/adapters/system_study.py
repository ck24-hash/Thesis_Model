"""Run type "blocks": the blocks in elements/ run by the engine in system/, from a system case (one input file per
block): every ticked block sized together, each block's year at its size, with and without each technology, the
site's yearly cost, the technical summary, the sensitivity of the sizes and the battery check (system/run_case.py).
The reference run type (battery_study.py) runs the reference battery model on the same case.

Ancillary services: off is the same overrides as for the reference, routed to the battery block."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from common import parameters as P
from elements.battery import sizing
from elements.grid import block as grid
from elements.ng_boiler import sizing as boiler_sizing
from general.commercial import block as commercial
from interface.adapters.battery_view import (battery_page, boiler_page, co2_page, effects_page, electricity_page,
                                             first_stage, heat_pump_page, results_for_page, storage_page,
                                             system_page)
from interface.tables import clean, read_table
from system import battery_check, dispatch, joint, run_case, setup
from system.run_case import run as run_studies
from system.run_case import summary_of, write_results

ID = "blocks"
NAME = "Blocks (elements/ and system/): joint sizing, the site's yearly cost and each block's study"
BLOCKS_REQUIRED = ["greenhouse", "grid"]
BLOCKS_ONE_OF: list = []   # no block to size is needed: the electricity side runs for every system
BLOCKS_ALLOWED = list(setup.BLOCKS)
ROOT = Path(__file__).resolve().parents[2]
# progress: a log line containing the marker moves the run to that stage
STAGES = [("Reading", 1), ("=== JOINT SIZING ===", 2), ("=== THE YEAR AT THE CHOSEN SIZES", 3),
          ("=== WITH AND WITHOUT", 4), ("=== SITE YEARLY COST", 5), ("=== SENSITIVITY", 6), ("=== BATTERY CHECK", 7),
          ("Writing", 8)]
STAGE_LABELS = [   # stage, label, counts the years solved, the block or option it belongs to
    (1, "Read the inputs", False, None),
    (2, "Sizing: every ticked block sized together, for the lowest yearly cost of the site", False, None),
    (3, "The year at the chosen sizes: each block's year, the electricity side", False, None),
    (4, "With and without each technology: the system without it sized again", False, None),
    (5, "The money: the site's yearly cost", False, None),
    (6, "Sensitivity: each size -10 % and +10 %, operation only", True, "sensitivity"),
    (7, "Battery check: the reference sweep", True, "battery_check"),
    (8, "Write summary_<tag>.json and results_<tag>.xlsx", False, None),
]


def track(run, text: str) -> None:
    """Moves the run's stage and counts the sizes solved per study, from one log line."""
    for marker, stage in STAGES:
        if marker in text:
            run.stage = max(run.stage, stage)
    if run.stage == 6 and " %: " in text:
        run.done["sensitivity"] = run.done.get("sensitivity", 0) + 1
    elif run.stage == 7 and " kWh ..." in text:
        run.done["battery_check"] = run.done.get("battery_check", 0) + 1


def options() -> dict:
    return {"id": ID, "name": NAME, "blocks_required": BLOCKS_REQUIRED, "blocks_one_of": BLOCKS_ONE_OF,
            "blocks_allowed": BLOCKS_ALLOWED, "markets": grid.markets(), "business_models": commercial.business_models(),
            "sizing_defaults": sizing.DEFAULTS,
            "stages": [dict(stage=s, label=label, counts=counts, block=b) for s, label, counts, b in STAGE_LABELS],
            "model_dir": str(ROOT / "elements")}


# -- parameters ------------------------------------------------------------------------------------------------------
def _sources(market: dict, business_model: str) -> dict:
    """The files each parameter group comes from, block by block."""
    c, r = market["country"], market["region"]
    groups: dict[str, list[Path]] = {"tariff": grid.tariff_files(market)}
    for key, m in {**setup.BLOCKS, **setup.GENERAL}.items():
        folder = getattr(m, "PARAMS_DIR", None)
        for group in m.OWNS:
            if group == "tariff" or folder is None:
                continue
            files = {"subsidies": [folder / "subsidies" / c / "_country.json", folder / "subsidies" / c / f"{r}.json"],
                     "ancillary": [folder / "ancillary" / f"{c}.json"],
                     "business_model": [folder / "business_models" / f"{business_model}.json"]}.get(
                group, [folder / group / "default.json", folder / group / f"{c}.json"])
            groups.setdefault(group, []).extend(files)
    out = {}
    for group, files in groups.items():
        found = [f for f in files if f.is_file()]
        about = [text for f in found if (text := P.read(f).get("_about"))]
        out[group] = {"files": [f.relative_to(ROOT).as_posix() for f in found], "about": about}
    return out


def parameters_for_page(market: dict, business_model: str = "direct_sales", overrides: dict | None = None) -> dict:
    defaults = setup.parameters(market, business_model)
    try:
        effective = setup.parameters(market, business_model, overrides or {})
        error = None
    except Exception as exc:   # a wrong override: show the defaults and say why
        effective, error = defaults, f"{type(exc).__name__}: {exc}"
    return clean({"currency": defaults["tariff"]["currency"], "defaults": defaults, "effective": effective,
                  "sources": _sources(market, business_model), "error": error})


# -- preview ---------------------------------------------------------------------------------------------------------
def _ancillary_on(s: setup.System) -> bool:
    return s.commercial.ancillary_rate > 0 or s.battery.tech.reserved_kwh(100.0) > 0


def preview(case: dict) -> dict:
    """What the run will do, without solving. case: a system case, input files absolute."""
    s = setup.from_tables(case, read_table)
    t, dt, c, sub = s.grid.tariff, s.dt, s.commercial, s.subsidies
    g = case["blocks"].get("grid") or {}
    regime_cfg = g.get("regime") or {}
    base, dup = dispatch.choose_regime(s, regime_cfg.get("auto", True), regime_cfg.get("manual"))
    import_max, export_max = dispatch.grid_limits_kw(s)
    export_pays_more, negative = dispatch.exclusive_steps(s, base)
    prices = {}
    for regime in t.regime_names:
        p = s.import_price(regime)
        prices[regime] = {"mean": p.mean(), "min": p.min(), "max": p.max(),
                          "weighted": (p * s.load).sum() / s.load.sum()}
    out = {
        "currency": s.currency,
        "site": {"load_mwh": s.greenhouse.yearly_load_kwh / 1000, "load_peak_kw": s.load.max(), "modules": s.modules,
                 "voltiris_kwp": s.modules * s.voltiris.module_wp / 1000 if s.voltiris else 0.0,
                 "voltiris_mwh": (s.volt_pv * dt).sum() / 1000,
                 "existing_mwh": (s.existing * dt).sum() / 1000 if s.existing is not None else 0.0,
                 "pv_mwh": (s.pv_total * dt).sum() / 1000,
                 "pv_surplus_mwh": ((s.pv_total - s.load).clip(lower=0) * dt).sum() / 1000},
        "money": {"pv_subsidy_mode": sub.pv["mode"], "pv_subsidy_frac": sub.pv.get("frac"),
                  "pv_capex": c.pv_capex(s.modules, s.voltiris.module_wp) if s.voltiris else 0.0,
                  "pv_life_yr": s.pv_life_yr},
        "tariff": {"regimes": t.regime_names, "has_rule": bool(t.rule), "threshold_h": t.dup_threshold_h,
                   "rule": t.rule, "uses_day_ahead": s.grid.uses_day_ahead, "battery_export": s.battery_export,
                   "import_price": prices, "export_value_mean": float(np.mean(s.bm.export_value)),
                   "capacity_charges": [name for name, _ in t.charges],
                   "business_model": s.bm.type, "eaas": s.bm.eaas},
        "regime": {"start": base, "dup_h": dup, "auto": regime_cfg.get("auto", True)},
        "grid": {"import_max_kw": import_max, "export_max_kw": export_max,
                 "import_auto": g.get("import_max_kw") is None, "export_auto": g.get("export_max_kw") is None},
        "meter": {"export_pays_more_h": len(export_pays_more) * dt, "negative_price_h": len(negative) * dt},
    }
    if s.battery is not None:
        tech, ref = s.battery.tech, 100.0
        cfg = {**sizing.DEFAULTS, **((case["blocks"].get("battery") or {}).get("sizing") or {})}
        sizes, cap = first_stage(cfg, sub.cap_sweep_at_subsidy, sub.battery_threshold_kwh)
        out["battery"] = {"c_rate": tech.c_rate, "soc_min": tech.soc_min, "soc_max": tech.soc_max,
                          "charge_efficiency": tech.eff_store, "discharge_efficiency": tech.eff_dispatch,
                          "round_trip": tech.eta2, "self_discharge_per_day": tech.self_discharge_per_hour * 24,
                          "per_100_kwh": {"window_kwh": tech.soc_window_kwh(ref), "power_kw": tech.power_kw(ref),
                                          "reserved_kwh": tech.reserved_kwh(ref), "reserved_kw": tech.reserved_kw(ref),
                                          "dispatch_kwh": tech.dispatch_kwh(ref), "dispatch_kw": tech.dispatch_kw(ref),
                                          "ancillary_revenue": s.ancillary_revenue(ref)}}
        out["ancillary"] = {"enabled": _ancillary_on(s), "rate_per_kw_year": c.ancillary_rate,
                            "mode": tech.reserve_mode, "frac": tech.reserve_frac, "kwh": tech.reserve_kwh}
        out["money"].update({
            "battery_tiers": c.capex["battery_tiers_per_kwh"],
            "price_per_kwh_at": {str(k): c.battery_price_per_kwh(k) for k in (100, 500, 1000, 2000)},
            "ems_hardware": s.ems.capex, "ems_fixed_per_year": s.ems.fixed_per_year,
            "subsidy_mode": sub.battery["mode"], "subsidy_frac": sub.battery.get("frac"),
            "subsidy_threshold_kwh": sub.battery_threshold_kwh, "price_after_subsidy_100": s.battery_net_capex(ref),
            "battery_life_yr": c.battery_life_yr})
        out["sizing"] = {**cfg, "sizes": sizes, "cap": cap}
    gh = s.greenhouse
    if s.heat_side:
        out["heat"] = {"heat_demand_mwh": (gh.heat * dt).sum() / 1000 if gh.heat is not None else None,
                       "heat_peak_kw": gh.heat.max() if gh.heat is not None else None,
                       "co2_demand_t": (gh.co2 * dt).sum() / 1000 if gh.co2 is not None else None,
                       "co2_peak_kg_h": gh.co2.max() if gh.co2 is not None else None}
    if s.heat_pump is not None:
        hp = s.heat_pump
        hcfg = (case["blocks"].get("heat_pump") or {}).get("sizing") or {}
        fixed = hcfg.get("objective") == "custom" and hcfg.get("custom_kw")
        el_for_heat = gh.heat / hp.cop                      # the electricity to give the whole demand
        hp_price = s.import_price(base) / hp.cop            # energy and network price per kWh of heat
        out["heat_pump"] = {
            "cop_mode": hp.cop_mode, "cop_nominal": hp.cop_nominal, "supply_temp_c": hp.supply_temp_c,
            "ref_outside_temp_c": hp.ref_outside_temp_c, "cop_mean": hp.cop.mean(), "cop_min": hp.cop_min,
            "cop_max": hp.cop.max(),
            "outside_temp": None if hp.outside_temp is None else {
                "mean": hp.outside_temp.mean(), "min": hp.outside_temp.min(), "max": hp.outside_temp.max()},
            "heat_demand_mwh": (gh.heat * dt).sum() / 1000, "heat_peak_kw": gh.heat.max(),
            "electricity_all_heat_mwh": (el_for_heat * dt).sum() / 1000, "electricity_heat_peak_kw": el_for_heat.max(),
            "heat_price_mean": hp_price.mean(), "heat_price_min": hp_price.min(), "heat_price_max": hp_price.max(),
            "capex_per_kw": c.capex["heat_pump_per_kw_th"], "fixed_om_per_kw_year": c.capex["heat_pump_fixed_om_per_kw_year"],
            "life_yr": c.heat_pump_life_yr, "sized": "fixed" if fixed else "joint",
            "custom_kw": hcfg.get("custom_kw") if fixed else None,
            "co2_source": bool(s.co2_blocks), "import_auto": g.get("import_max_kw") is None, "import_max_kw": import_max}
        if s.boiler is not None:   # the boiler's running cost per kWh of heat, and how often the heat pump's is lower
            boiler_price = s.gas.cost_per_kwh / s.boiler.efficiency + c.boiler_var_om_per_kwh
            out["heat_pump"].update(boiler_heat_price_mean=boiler_price.mean(),
                                    cheaper_h=float((hp_price < boiler_price).sum() * dt))
    if s.boiler is not None:
        out["boiler"] = {
            "needed_kw": boiler_sizing.needed_kw(s), "efficiency": s.boiler.efficiency, "co2_use_frac": s.boiler.co2_use_frac,
            "co2_mode": gh.co2_mode, "heat_demand_mwh": (gh.heat * dt).sum() / 1000, "heat_peak_kw": gh.heat.max(),
            "co2_demand_t": (gh.co2 * dt).sum() / 1000, "co2_peak_kg_h": gh.co2.max(),
            "gas_price_mean": s.gas.price.mean(), "gas_price_min": s.gas.price.min(), "gas_price_max": s.gas.price.max(),
            "emission_factor": s.gas.emission_factor, "levy_per_kg": s.gas.levy_per_kg,
            "capex_per_kw": c.capex["boiler_per_kw_th"], "life_yr": c.boiler_life_yr}
    plan = joint.plan_of(s, case["blocks"])
    out["joint_sizing"] = {"mode": "joint", "plan": plan,
                           "battery_max_kwh": joint.battery_limit(s, case["blocks"]) if s.battery else None,
                           "sensitivity": run_case.sensitivity_on(case),
                           "battery_check": s.battery is not None and plan.get("battery", 0) is None
                           and battery_check.enabled(case)}
    if s.external_co2 is not None:
        x, gh = s.external_co2, s.greenhouse
        out["co2"] = {"price_mean": x.price.mean(), "price_min": x.price.min(), "price_max": x.price.max(),
                      "co2_demand_t": (gh.co2 * dt).sum() / 1000, "co2_peak_kg_h": gh.co2.max(),
                      "fixed_per_year": x.fixed_per_year, "max_kg_h": x.max_kg_h}
        if s.boiler is not None:   # what burning gas for CO2 costs per kg when the heat is not needed
            per_kg = s.gas.emission_factor * s.boiler.co2_use_frac
            eq = (s.gas.cost_per_kwh + c.boiler_var_om_per_kwh * s.boiler.efficiency) / per_kg
            out["co2"].update(gas_eq_mean=eq.mean(), gas_eq_min=eq.min(), gas_eq_max=eq.max())
    if s.storage is not None:
        t = s.storage
        temp = t.outside_temp
        out["storage"] = {
            "heat_peak_kw": float(s.greenhouse.heat.max()), "charge_efficiency": t.eff_charge,
            "discharge_efficiency": t.eff_discharge, "power_per_kwh": t.power_per_kwh, "loss_mode": t.loss_mode,
            "loss_mean": t.loss_per_hour.mean(), "loss_min": t.loss_per_hour.min(), "loss_max": t.loss_per_hour.max(),
            "outside_temp": None if temp is None else {"mean": temp.mean(), "min": temp.min(), "max": temp.max()},
            "capex_per_kwh": c.capex["thermal_storage_per_kwh"], "life_yr": c.thermal_storage_life_yr}
    return clean(out)


# -- running ---------------------------------------------------------------------------------------------------------
def run(case_path: Path, out_dir: Path, tag: str, log) -> tuple[dict, dict]:
    """The studies, as system/run_case.py runs them. Returns (results for the page, files written)."""
    case = setup.load_case(case_path)
    out, s = run_studies(case, case_path.parent, tag, log=log)
    log("\nWriting the result files ...")
    write_results(out, out_dir, tag)
    summary_path, workbook_path = out_dir / f"summary_{tag}.json", out_dir / f"results_{tag}.xlsx"
    log(f"  {summary_path}\n  {workbook_path}")
    battery = None
    if out["battery"] is not None:
        sizing_settings = (case["blocks"].get("battery") or {}).get("sizing")
        cfg = {**sizing.DEFAULTS, **(sizing_settings or {})}
        sizes, cap = first_stage(cfg, s.subsidies.cap_sweep_at_subsidy, s.subsidies.battery_threshold_kwh)
        choice = {"objective": cfg["objective"], "custom_kwh": cfg["custom_kwh"],
                  "battery_life_yr": s.commercial.battery_life_yr, "cap": cap, "first_stage": sizes,
                  "fine_grid_kwh": cfg["fine_grid_kwh"], "fine_window_kwh": cfg["fine_window_kwh"],
                  "regime_rule": bool(s.grid.tariff.rule), "threshold_h": s.grid.tariff.dup_threshold_h,
                  "dispatch_kwh_per_kwh": s.battery.tech.dispatch_kwh(1.0), "ancillary_on": _ancillary_on(s),
                  "joint": True, "plan": out["joint"]["plan"].get("battery")}
        battery = battery_page(out["battery"], s.dt, choice)
    boiler = boiler_page(out["boiler"], s.dt) if out["boiler"] is not None else None
    storage = storage_page(out["thermal_storage"], s.dt) if out["thermal_storage"] is not None else None
    heat_pump = heat_pump_page(out["heat_pump"], s) if out["heat_pump"] is not None else None
    page = results_for_page(ID, battery=battery, boiler=boiler, storage=storage, heat_pump=heat_pump,
                            electricity=electricity_page(out["electricity"]), summary=summary_of(out),
                            system=system_page(out["mode"], out["costs"], out["joint"], out["technical"],
                                               out["sensitivity"], out["battery_check"]),
                            effects=effects_page(out["effects"], out["mode"]) if out.get("effects") else None,
                            co2=co2_page(out["heat_side"], s) if s.external_co2 is not None else None)
    return page, {"summary": str(summary_path), "results": str(workbook_path)}
