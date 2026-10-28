"""Run type "battery study": Voltiris + battery + grid (+ existing PV) on the site's electricity load, run by
elements/battery_reference (Jesse's model). Nothing in it is changed: this file only imports it. It is the only file of
the interface that knows that model.

The page gives a system case (one input file per block); that model reads one workbook, so the blocks' inputs are
put together in its format (system/setup.py reference_frame) and the case is translated (to_battery_case).

Ancillary services: the model always applies params/ancillary/<country>.json. The page's switch "off" writes the
overrides {"ancillary": {"rate_per_kw_year": 0, "reserve": {"mode": "percent", "frac": 0}}} into the case file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from interface.adapters.battery_view import STAGE_LABELS, first_stage, results_for_page, track  # noqa: F401
from interface.tables import clean, read_table
from system import compare, setup

MODEL_DIR = Path(__file__).resolve().parents[2] / "elements" / "battery_reference"
sys.path.insert(0, str(MODEL_DIR))

import parameters  # noqa: E402
import run_case  # noqa: E402
from blocks import capex as capex_block  # noqa: E402
from engine import dispatch, pipeline, sizing  # noqa: E402
from engine.setup import Setup  # noqa: E402

ID = "battery_study"
NAME = "Battery study, reference model (elements/battery_reference)"
BLOCKS_REQUIRED = ["greenhouse", "grid", "battery"]
BLOCKS_ALLOWED = ["greenhouse", "voltiris", "existing_pv", "grid", "battery"]
PARAMS_DIR = parameters.PARAMS_DIR


def options() -> dict:
    markets = []
    for path in sorted((PARAMS_DIR / "tariffs").glob("*/*/*.json")):
        if path.name.startswith("_"):
            continue
        utility, _, year = path.stem.rpartition("_")
        markets.append({"country": path.parts[-3], "region": path.parts[-2], "utility": utility, "year": int(year)})
    return {"id": ID, "name": NAME, "blocks_required": BLOCKS_REQUIRED, "blocks_allowed": BLOCKS_ALLOWED,
            "markets": markets, "business_models": sorted(p.stem for p in (PARAMS_DIR / "business_models").glob("*.json")),
            "sizing_defaults": sizing.DEFAULTS,
            "stages": [dict(stage=s, label=label, counts=counts) for s, label, counts in STAGE_LABELS],
            "model_dir": str(MODEL_DIR)}


# -- parameters ------------------------------------------------------------------------------------------------------
def _sources(market: dict, business_model: str) -> dict:
    c, r, u, y = market["country"], market["region"], market["utility"], market["year"]
    candidates = {
        "tariff": [f"tariffs/{c}/_country.json", f"tariffs/{c}/{r}/_canton.json", f"tariffs/{c}/{r}/_region.json",
                   f"tariffs/{c}/{r}/{u}_{y}.json"],
        "subsidies": [f"subsidies/{c}/_country.json", f"subsidies/{c}/{r}.json"],
        "ancillary": [f"ancillary/{c}.json"],
        "business_model": [f"business_models/{business_model}.json"],
    }
    for block in ("capex", "finance", "tech", "ems"):
        candidates[block] = [f"{block}/default.json", f"{block}/{c}.json"]
    out = {}
    for block, files in candidates.items():
        found = [f for f in files if (PARAMS_DIR / f).is_file()]
        about = [text for f in found
                 if (text := json.loads((PARAMS_DIR / f).read_text(encoding="utf-8")).get("_about"))]
        out[block] = {"files": ["elements/battery_reference/params/" + f for f in found], "about": about}
    return out


def parameters_for_page(market: dict, business_model: str = "direct_sales", overrides: dict | None = None) -> dict:
    args = (market["country"], market["region"], market["utility"], int(market["year"]))
    defaults = parameters.load(*args, business_model=business_model)
    try:
        effective = parameters.load(*args, business_model=business_model, overrides=overrides or {})
        error = None
    except Exception as exc:   # a wrong override: show the defaults and say why
        effective, error = defaults, f"{type(exc).__name__}: {exc}"
    return clean({"currency": defaults["tariff"]["currency"], "defaults": defaults, "effective": effective,
                  "sources": _sources(market, business_model), "error": error})


# -- the Setup built from the page's case ----------------------------------------------------------------------------
def _setup(case: dict) -> tuple[Setup, dict]:
    """The reference Setup of a system case (input files absolute, kept in memory), and the case in its format."""
    return compare.reference_setup(case, Path("."), read_table)


def _first_stage(s: Setup, cfg: dict) -> tuple[list, int | None]:
    """The sizes engine/sizing.py sweep() solves first, and the subsidy cap."""
    return first_stage(cfg, s.cap_sweep_at_subsidy, s.subsidy_threshold_kwh)


def _ancillary_on(s: Setup) -> bool:
    return s.ancillary.get("rate_per_kw_year", 0) > 0 or s.battery.reserved_kwh(100.0) > 0


def preview(case: dict) -> dict:
    """case: a system case, input files absolute."""
    s, ref = _setup(case)
    st, b, t, dt = s.study, s.battery, s.tariff, s.dt
    regime_cfg = ref.get("regime") or {}
    base, dup = pipeline.choose_regime(s, regime_cfg.get("auto", True), regime_cfg.get("manual"))
    cfg = {**sizing.DEFAULTS, **(ref.get("sizing") or {})}
    sizes, cap = _first_stage(s, cfg)
    import_max, export_max = dispatch.grid_limits_kw(s)
    export_pays_more, negative = dispatch.exclusive_steps(s, base)
    prices = {}
    for regime in t.regime_names:
        p = s.import_price(regime)
        prices[regime] = {"mean": p.mean(), "min": p.min(), "max": p.max(),
                          "weighted": (p * st.load).sum() / st.load.sum()}
    ref = 100.0
    return clean({
        "currency": s.currency,
        "site": {"load_mwh": st.yearly_load_kwh / 1000, "load_peak_kw": st.load.max(), "modules": st.modules,
                 "voltiris_kwp": st.modules * s.module_wp / 1000, "voltiris_mwh": (st.volt_pv * dt).sum() / 1000,
                 "existing_mwh": (st.existing_pv * dt).sum() / 1000 if st.existing_pv is not None else 0.0,
                 "pv_mwh": (st.pv_total * dt).sum() / 1000,
                 "pv_surplus_mwh": ((st.pv_total - st.load).clip(lower=0) * dt).sum() / 1000},
        "battery": {"c_rate": b.c_rate, "soc_min": b.soc_min, "soc_max": b.soc_max,
                    "charge_efficiency": b.eff_store, "discharge_efficiency": b.eff_dispatch, "round_trip": b.eta2,
                    "self_discharge_per_day": b.self_discharge_per_hour * 24,
                    "per_100_kwh": {"window_kwh": b.soc_window_kwh(ref), "power_kw": b.power_kw(ref),
                                    "reserved_kwh": b.reserved_kwh(ref), "reserved_kw": b.reserved_kw(ref),
                                    "dispatch_kwh": b.dispatch_kwh(ref), "dispatch_kw": b.dispatch_kw(ref),
                                    "ancillary_revenue": s.ancillary_revenue(ref)}},
        "ancillary": {"enabled": _ancillary_on(s), "rate_per_kw_year": s.ancillary.get("rate_per_kw_year", 0),
                      "mode": b.reserve_mode, "frac": b.reserve_frac, "kwh": b.reserve_kwh},
        "money": {"battery_tiers": s.capex["battery_tiers_per_kwh"],
                  "price_per_kwh_at": {str(k): capex_block.battery_price_per_kwh(k, s.capex)
                                       for k in (100, 500, 1000, 2000)},
                  "ems_hardware": s.ems.capex, "ems_fixed_per_year": s.ems.fixed_per_year,
                  "subsidy_mode": s.subsidies["battery"]["mode"], "subsidy_frac": s.subsidies["battery"].get("frac"),
                  "subsidy_threshold_kwh": s.subsidy_threshold_kwh, "price_after_subsidy_100": s.battery_net_capex(ref),
                  "pv_subsidy_mode": s.subsidies["pv"]["mode"], "pv_subsidy_frac": s.subsidies["pv"].get("frac"),
                  "pv_capex": capex_block.pv_gross(st.modules, s.module_wp, s.capex),
                  "battery_life_yr": s.finance["battery_life_yr"], "pv_life_yr": s.finance["pv_life_yr"]},
        "tariff": {"regimes": t.regime_names, "has_rule": bool(t.rule), "threshold_h": t.dup_threshold_h,
                   "rule": t.rule, "uses_day_ahead": s.uses_day_ahead, "battery_export": s.battery_export,
                   "import_price": prices, "export_value_mean": float(np.mean(s.bm.export_value)),
                   "capacity_charges": [name for name, _ in t.charges],
                   "business_model": s.bm.type, "eaas": s.bm.eaas},
        "regime": {"start": base, "dup_h": dup, "auto": regime_cfg.get("auto", True)},
        "grid": {"import_max_kw": import_max, "export_max_kw": export_max,
                 "import_auto": (ref.get("grid") or {}).get("import_max_kw") is None,
                 "export_auto": (ref.get("grid") or {}).get("export_max_kw") is None},
        "meter": {"export_pays_more_h": len(export_pays_more) * dt, "negative_price_h": len(negative) * dt},
        "sizing": {**cfg, "sizes": sizes, "cap": cap},
    })


# -- running ---------------------------------------------------------------------------------------------------------
def run(case_path: Path, out_dir: Path, tag: str, log) -> tuple[dict, dict]:
    """The study, exactly as elements/battery_reference/run_case.py runs it on the case translated to its format and
    the blocks' inputs written as one workbook (input_<tag>.xlsx, case_<tag>_reference.json next to the results).
    Returns (results for the page, files written)."""
    case = setup.load_case(case_path)
    log(f"  Writing the reference model's input workbook input_{tag}.xlsx ...")
    setup.reference_frame(case, setup.excel_reader()).to_excel(out_dir / f"input_{tag}.xlsx", index=False)
    ref = {**setup.to_battery_case(case), "input_file": f"input_{tag}.xlsx", "tag": tag, "output_dir": str(out_dir)}
    ref_path = out_dir / f"case_{tag}_reference.json"
    ref_path.write_text(json.dumps(ref, indent=2), encoding="utf-8")
    saved = run_case.load_case(ref_path)
    s = run_case.setup_from_case(saved, ref_path.parent)
    log(f"  Ancillary services: {'on' if _ancillary_on(s) else 'off (rate and reserve set to 0 by overrides)'}")
    regime = saved.get("regime", {})
    out = pipeline.run(s, regime_auto=regime.get("auto", True), regime_manual=regime.get("manual"),
                       sizing_settings=saved.get("sizing"), tag=tag, log=log)
    log("\nWriting the result files ...")
    run_case.write_results(out, out_dir, tag)
    summary_path, workbook_path = out_dir / f"summary_{tag}.json", out_dir / f"results_{tag}.xlsx"
    log(f"  {summary_path}\n  {workbook_path}")
    return _results_for_page(out, s, saved.get("sizing")), {"summary": str(summary_path), "results": str(workbook_path)}


def _results_for_page(out: dict, s: Setup, sizing_settings: dict | None) -> dict:
    cfg = {**sizing.DEFAULTS, **(sizing_settings or {})}
    sizes, cap = _first_stage(s, cfg)
    choice = {"objective": cfg["objective"], "custom_kwh": cfg["custom_kwh"],
              "battery_life_yr": s.finance["battery_life_yr"], "cap": cap, "first_stage": sizes,
              "fine_grid_kwh": cfg["fine_grid_kwh"], "fine_window_kwh": cfg["fine_window_kwh"],
              "regime_rule": bool(s.tariff.rule), "threshold_h": s.tariff.dup_threshold_h,
              "dispatch_kwh_per_kwh": s.battery.dispatch_kwh(1.0), "ancillary_on": _ancillary_on(s)}
    return results_for_page(out, s.dt, choice, ID)
