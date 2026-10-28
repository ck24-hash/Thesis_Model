"""Run type "blocks": the battery study run by the blocks in elements/ and the engine in system/. It takes the same
case as the reference run type (battery_study.py) and gives the same results (checked with system/compare.py).

Ancillary services: off is the same overrides as for the reference, routed to the battery block."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from common import parameters as P
from elements.battery import sizing, study
from elements.grid import block as grid
from elements.voltiris import block as voltiris
from interface.adapters.battery_view import STAGE_LABELS, TIME_ROLES, first_stage, results_for_page, track  # noqa: F401
from interface.tables import clean, read_table
from system import dispatch, setup
from system.run_case import write_results

ID = "blocks"
NAME = "Battery study, blocks (elements/ and system/)"
BLOCKS_REQUIRED = ["greenhouse", "grid", "battery"]
BLOCKS_ALLOWED = list(setup.BLOCKS)
DEFAULT_COLUMNS = setup.default_columns()
COLUMN_ROLES = TIME_ROLES + [(c["role"], c["about"], c["unit"], c["kind"], c["needed"], key)
                             for key, m in setup.BLOCKS.items() for c in m.COLUMNS]
ROOT = Path(__file__).resolve().parents[2]


def options() -> dict:
    return {"id": ID, "name": NAME, "blocks_required": BLOCKS_REQUIRED, "blocks_allowed": BLOCKS_ALLOWED,
            "markets": grid.markets(), "business_models": voltiris.business_models(),
            "sizing_defaults": sizing.DEFAULTS, "default_columns": DEFAULT_COLUMNS,
            "column_roles": [dict(role=r, about=a, unit=u, kind=k, needed=n, block=b) for r, a, u, k, n, b in COLUMN_ROLES],
            "stages": [dict(stage=s, label=label, counts=counts) for s, label, counts in STAGE_LABELS],
            "model_dir": str(ROOT / "elements")}


# -- parameters ------------------------------------------------------------------------------------------------------
def _sources(market: dict, business_model: str) -> dict:
    """The files each parameter group comes from, block by block."""
    c, r = market["country"], market["region"]
    groups: dict[str, list[Path]] = {"tariff": grid.tariff_files(market)}
    for key, m in setup.BLOCKS.items():
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
    return s.battery.ancillary.get("rate_per_kw_year", 0) > 0 or s.battery.tech.reserved_kwh(100.0) > 0


def preview(case: dict) -> dict:
    s = setup.from_frame(read_table(case["input_file"]), case)
    b, t, dt = s.battery, s.grid.tariff, s.dt
    tech = b.tech
    regime_cfg = case.get("regime") or {}
    base, dup = study.choose_regime(s, regime_cfg.get("auto", True), regime_cfg.get("manual"))
    cfg = {**sizing.DEFAULTS, **(case.get("sizing") or {})}
    sizes, cap = first_stage(cfg, b.cap_sweep_at_subsidy, b.subsidy_threshold_kwh)
    import_max, export_max = dispatch.grid_limits_kw(s)
    export_pays_more, negative = dispatch.exclusive_steps(s, base)
    prices = {}
    for regime in t.regime_names:
        p = s.import_price(regime)
        prices[regime] = {"mean": p.mean(), "min": p.min(), "max": p.max(),
                          "weighted": (p * s.load).sum() / s.load.sum()}
    ref = 100.0
    return clean({
        "currency": s.currency,
        "site": {"load_mwh": s.greenhouse.yearly_load_kwh / 1000, "load_peak_kw": s.load.max(), "modules": s.modules,
                 "voltiris_kwp": s.modules * s.voltiris.module_wp / 1000 if s.voltiris else 0.0,
                 "voltiris_mwh": (s.volt_pv * dt).sum() / 1000,
                 "existing_mwh": (s.existing * dt).sum() / 1000 if s.existing is not None else 0.0,
                 "pv_mwh": (s.pv_total * dt).sum() / 1000,
                 "pv_surplus_mwh": ((s.pv_total - s.load).clip(lower=0) * dt).sum() / 1000},
        "battery": {"c_rate": tech.c_rate, "soc_min": tech.soc_min, "soc_max": tech.soc_max,
                    "charge_efficiency": tech.eff_store, "discharge_efficiency": tech.eff_dispatch,
                    "round_trip": tech.eta2, "self_discharge_per_day": tech.self_discharge_per_hour * 24,
                    "per_100_kwh": {"window_kwh": tech.soc_window_kwh(ref), "power_kw": tech.power_kw(ref),
                                    "reserved_kwh": tech.reserved_kwh(ref), "reserved_kw": tech.reserved_kw(ref),
                                    "dispatch_kwh": tech.dispatch_kwh(ref), "dispatch_kw": tech.dispatch_kw(ref),
                                    "ancillary_revenue": b.ancillary_revenue(ref)}},
        "ancillary": {"enabled": _ancillary_on(s), "rate_per_kw_year": b.ancillary.get("rate_per_kw_year", 0),
                      "mode": tech.reserve_mode, "frac": tech.reserve_frac, "kwh": tech.reserve_kwh},
        "money": {"battery_tiers": b.capex["battery_tiers_per_kwh"],
                  "price_per_kwh_at": {str(k): b.price_per_kwh(k) for k in (100, 500, 1000, 2000)},
                  "ems_hardware": b.ems.capex, "ems_fixed_per_year": b.ems.fixed_per_year,
                  "subsidy_mode": b.subsidies["battery"]["mode"], "subsidy_frac": b.subsidies["battery"].get("frac"),
                  "subsidy_threshold_kwh": b.subsidy_threshold_kwh, "price_after_subsidy_100": b.net_capex(ref),
                  "battery_life_yr": b.life_yr, "pv_life_yr": s.pv_life_yr},
        "tariff": {"regimes": t.regime_names, "has_rule": bool(t.rule), "threshold_h": t.dup_threshold_h,
                   "rule": t.rule, "uses_day_ahead": s.grid.uses_day_ahead, "battery_export": s.battery_export,
                   "import_price": prices, "export_value_mean": float(np.mean(s.bm.export_value)),
                   "capacity_charges": [name for name, _ in t.charges],
                   "business_model": s.bm.type, "eaas": s.bm.eaas},
        "regime": {"start": base, "dup_h": dup, "auto": regime_cfg.get("auto", True)},
        "grid": {"import_max_kw": import_max, "export_max_kw": export_max,
                 "import_auto": (case.get("grid") or {}).get("import_max_kw") is None,
                 "export_auto": (case.get("grid") or {}).get("export_max_kw") is None},
        "meter": {"export_pays_more_h": len(export_pays_more) * dt, "negative_price_h": len(negative) * dt},
        "sizing": {**cfg, "sizes": sizes, "cap": cap},
    })


# -- running ---------------------------------------------------------------------------------------------------------
def run(case_path: Path, out_dir: Path, tag: str, log) -> tuple[dict, dict]:
    """The battery study with the blocks, as system/run_case.py runs it. Returns (results for the page, files)."""
    case = setup.load_case(case_path)
    s = setup.build(case, case_path.parent)
    log(f"  Blocks: {', '.join(s.chosen)}")
    log(f"  Ancillary services: {'on' if _ancillary_on(s) else 'off (rate and reserve set to 0 by overrides)'}")
    regime = (case["blocks"].get("grid") or {}).get("regime") or {}
    sizing_settings = (case["blocks"].get("battery") or {}).get("sizing")
    out = study.run(s, regime_auto=regime.get("auto", True), regime_manual=regime.get("manual"),
                    sizing_settings=sizing_settings, tag=tag, log=log)
    log("\nWriting the result files ...")
    write_results(out, out_dir, tag)
    summary_path, workbook_path = out_dir / f"summary_{tag}.json", out_dir / f"results_{tag}.xlsx"
    log(f"  {summary_path}\n  {workbook_path}")
    cfg = {**sizing.DEFAULTS, **(sizing_settings or {})}
    sizes, cap = first_stage(cfg, s.battery.cap_sweep_at_subsidy, s.battery.subsidy_threshold_kwh)
    choice = {"objective": cfg["objective"], "custom_kwh": cfg["custom_kwh"],
              "battery_life_yr": s.battery.life_yr, "cap": cap, "first_stage": sizes,
              "fine_grid_kwh": cfg["fine_grid_kwh"], "fine_window_kwh": cfg["fine_window_kwh"],
              "regime_rule": bool(s.grid.tariff.rule), "threshold_h": s.grid.tariff.dup_threshold_h,
              "dispatch_kwh_per_kwh": s.battery.tech.dispatch_kwh(1.0), "ancillary_on": _ancillary_on(s)}
    return results_for_page(out, s.dt, choice, ID), {"summary": str(summary_path), "results": str(workbook_path)}
