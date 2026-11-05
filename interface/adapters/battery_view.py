"""What the run types share on the page: the column roles of the time stamps, the reference run type's progress
stages, and the results the page draws, each in its own part: the electricity side (every run), the battery study,
the gas boiler study, the heat pump's year and the heat storage study."""
from __future__ import annotations

import pandas as pd

from interface.tables import clean, rounded

# role, what it is, unit, kind (how common/timeseries.py brings it to 15 min), when it is needed, block
TIME_ROLES = [
    ("month", "month of the row", "1-12", "time", "always", "time"),
    ("day", "day of the month", "1-31", "time", "always", "time"),
    ("hour", "hour of the day", "0-23", "time", "always", "time"),
    ("minute", "minute of the hour", "0, 15, 30, 45", "time", "15-min data; 0 when missing", "time"),
]
# the reference model's progress: a log line containing the marker moves the run to that stage
STAGES = [("Reading", 1), ("Auto DUP", 1), ("Regime ", 1), ("Solving the year without battery", 2),
          ("BATTERY SIZING SWEEP", 3), ("Chosen:", 4), ("=== ELECTRICITY", 5), ("=== SITE YEARLY COST", 5),
          ("Writing", 6)]
STAGE_LABELS = [   # stage, label, counts the sizes solved, the block it belongs to
    (1, "Read the inputs, find the starting regime", False, None),
    (2, "Optimise the year without battery: the baseline bill", False, "battery"),
    (3, "Size sweep: optimise the year for each size", True, "battery"),
    (4, "Optimise the chosen size; its bill, value, PV saving and payback scenarios", False, "battery"),
    (5, "Electricity side and the site's yearly cost", False, None),
    (6, "Write summary_<tag>.json and results_<tag>.xlsx", False, None),
]


def track(run, text: str) -> None:
    """Moves the run's stage and counts the battery sizes solved, from one log line."""
    for marker, stage in STAGES:
        if marker in text:
            run.stage = max(run.stage, stage)
    if " kWh ..." in text:
        run.done["battery"] = run.done.get("battery", 0) + 1


def first_stage(cfg: dict, cap_at_subsidy: bool, threshold_kwh: float) -> tuple[list, int | None]:
    """The battery sizes the sweep solves first, and the subsidy cap (the rule of the sweep in both models)."""
    coarse = sorted(set(cfg["sweep_kwh"]) | ({cfg["custom_kwh"]} if cfg["objective"] == "custom" else set()))
    cap = None
    if cfg["cap_at_subsidy_size"] and cap_at_subsidy:
        cap = round(threshold_kwh)
        coarse = sorted({size for size in coarse if size <= cap} | {cap})
    return coarse, cap


def battery_page(out: dict, dt: float, choice: dict) -> dict:
    """The battery study's results for the page."""
    d = out["dispatch"]
    hourly = d.resample("h").mean()
    energy = pd.DataFrame({"load": d["load"], "pv": d["pv"], "grid_import": d["grid_import"],
                           "grid_export": d["grid_export"], "charged": (-d["battery_power"]).clip(lower=0),
                           "discharged": d["battery_power"].clip(lower=0)}) * dt
    daily = energy.resample("D").sum()
    soc_max = d["battery_soc"].resample("D").max()
    return {
        "choice": choice,
        "daily": {"start": daily.index[0].isoformat(), **{c: rounded(daily[c], 1) for c in daily.columns},
                  "soc_max": rounded(soc_max, 1)},
        "summary": out["summary"],
        "bills": out["bills"],
        "monthly_no_battery": out["monthly_no_battery"],
        "monthly_battery": out["monthly_battery"],
        "payback": out["payback"],
        "baseline": out["baseline"],
        "dispatch": {"start": hourly.index[0].isoformat(), **{c: rounded(hourly[c], 3) for c in hourly.columns}},
    }


def boiler_page(out: dict, dt: float) -> dict:
    """The gas boiler study's results for the page: heat in MWh per day, CO2 in t per day."""
    d = out["dispatch"]
    daily = (d[["heat_demand", "boiler_heat", "hp_heat", "heat_release", "heat_unmet", "gas",
                "co2_demand", "co2_supplied", "co2_vented"]] * dt / 1000).resample("D").sum()
    return {
        "choice": out["choice"],
        "summary": out["summary"],
        "monthly": out["monthly"],
        "daily": {"start": daily.index[0].isoformat(), **{c: rounded(daily[c], 3) for c in daily.columns}},
    }


def electricity_page(e: dict) -> dict:
    """The electricity side for the page: per case (without battery, with battery) its key figures, bills, month by
    month table and the hourly split (kW) for the week chart."""
    out = {}
    for key, c in e["cases"].items():
        hourly = c["split"][["load", "voltiris_to_load", "existing_to_load", "battery_to_load", "grid_to_load",
                             "pv_to_battery", "pv_exported", "battery_to_grid", "grid_to_battery", "pv",
                             "battery_soc", "heat_pump"]].resample("h").mean()
        out[key] = {"kpi": c["kpi"], "bills": c["bills"], "monthly": c["monthly"],
                    "pv_savings": c.get("pv_savings"), "battery_savings": c.get("battery_savings"),
                    "hourly": {"start": hourly.index[0].isoformat(), **{k: rounded(hourly[k], 2) for k in hourly}}}
    return {"cases": out}


def storage_page(out: dict, dt: float) -> dict:
    """The heat storage study's results for the page: heat in MWh per day, the highest heat stored per day."""
    d, b = out["dispatch"], out["baseline"]
    daily = (d[["storage_charge", "storage_discharge", "heat_release"]] * dt / 1000).resample("D").sum()
    daily["heat_release_no_storage"] = (b["heat_release"] * dt / 1000).resample("D").sum()
    daily["soc_max"] = d["storage_soc"].resample("D").max() / 1000
    hourly = d[["heat_demand", "boiler_heat", "storage_charge", "storage_discharge", "heat_release", "heat_unmet",
                "storage_soc", "gas"]].resample("h").mean()
    hourly["boiler_heat_no_storage"] = b["boiler_heat"].resample("h").mean()
    if d["hp_heat"].any() or b["hp_heat"].any():   # the heat pump as a heat source too
        hourly["hp_heat"] = d["hp_heat"].resample("h").mean()
        hourly["hp_heat_no_storage"] = b["hp_heat"].resample("h").mean()
    return {
        "choice": out["choice"],
        "summary": out["summary"],
        "monthly": out["monthly"],
        "value_parts": out.get("value_parts", {}),
        "fuel": out.get("fuel"),
        "daily": {"start": daily.index[0].isoformat(), **{c: rounded(daily[c], 3) for c in daily.columns}},
        "hourly": {"start": hourly.index[0].isoformat(), **{c: rounded(hourly[c], 2) for c in hourly.columns}},
    }


def heat_pump_page(out: dict, s) -> dict:
    """The heat pump's year for the page: heat and electricity in MWh per day, the COP per day, and hourly for the
    week chart."""
    d, dt = out["dispatch"], s.dt
    cop = out["cop"].reindex(d.index)
    cols = ["heat_demand", "hp_heat", "boiler_heat", "heat_release", "heat_unmet", "hp_electricity"]
    if "storage_discharge" in d.columns:
        cols += ["storage_discharge", "storage_charge"]
    daily = (d[cols] * dt / 1000).resample("D").sum()
    daily["cop"] = cop.resample("D").mean()
    hourly = d[cols].resample("h").mean()
    hourly["cop"] = cop.resample("h").mean()
    if s.heat_pump.outside_temp is not None:
        temp = s.heat_pump.outside_temp.reindex(d.index)
        daily["outside_temp"] = temp.resample("D").mean()
        hourly["outside_temp"] = temp.resample("h").mean()
    return {
        "summary": out["summary"],
        "monthly": out["monthly"],
        "cop_curve": out["cop_curve"],
        "daily": {"start": daily.index[0].isoformat(), **{c: rounded(daily[c], 3) for c in daily.columns}},
        "hourly": {"start": hourly.index[0].isoformat(), **{c: rounded(hourly[c], 2) for c in hourly.columns}},
    }


def co2_page(heat: pd.DataFrame, s) -> dict:
    """Where the greenhouse's CO2 comes from (the boiler's flue gas or bought), per day and per month, with the price
    of bought CO2 and what burning gas for CO2 would cost per kg (when the heat is not needed)."""
    dt, x = s.dt, s.external_co2
    flue = (heat["co2_supplied"] - heat["co2_bought"]).clip(lower=0)
    frame = pd.DataFrame({"co2_demand": heat["co2_demand"], "from_flue_gas": flue, "bought": heat["co2_bought"],
                          "unmet": heat["co2_unmet"], "vented": heat["co2_vented"]}) * dt / 1000
    price = x.price.reindex(heat.index)
    gas_eq = None
    if s.boiler is not None:   # gas, levy and boiler O&M per kg of usable flue gas CO2
        per_kg = s.gas.emission_factor * s.boiler.co2_use_frac
        gas_eq = (s.gas.cost_per_kwh.reindex(heat.index)
                  + s.commercial.boiler_var_om_per_kwh * s.boiler.efficiency) / per_kg
    daily = frame.resample("D").sum()
    daily["price"] = price.resample("D").mean()
    if gas_eq is not None:
        daily["gas_equivalent"] = gas_eq.resample("D").mean()
    months = frame.index.month
    monthly = frame.groupby(months).sum()
    monthly["cost"] = (heat["co2_bought"] * price * dt).groupby(months).sum()
    alternative = None
    if gas_eq is not None:   # burning gas only for the CO2 bought, its heat not needed
        alternative = heat["co2_bought"] * gas_eq * dt
        monthly["alternative"] = alternative.groupby(months).sum()
        monthly["saving"] = monthly["alternative"] - monthly["cost"]
    monthly["price"] = price.groupby(months).mean()
    if gas_eq is not None:
        monthly["gas_equivalent"] = gas_eq.groupby(months).mean()
    monthly.index = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly = monthly.rename(columns={"co2_demand": "CO2 demand (t)", "from_flue_gas": "From flue gas (t)",
                                      "bought": "Bought (t)", "unmet": "Unmet (t)", "vented": "Vented (t)",
                                      "cost": "Cost of CO2 bought", "alternative": "Burning gas instead",
                                      "saving": "Saving", "price": "CO2 price, per kg",
                                      "gas_equivalent": "Gas as CO2, per kg"})
    total = frame.sum()
    bought_cost = float((heat["co2_bought"] * price * dt).sum())
    return {
        "summary": {"co2_demand_t": total["co2_demand"], "from_flue_gas_t": total["from_flue_gas"],
                    "bought_t": total["bought"], "unmet_t": total["unmet"], "vented_t": total["vented"],
                    "bought_cost": bought_cost, "price_mean": float(price.mean()),
                    "price_paid": bought_cost / (total["bought"] * 1000) if total["bought"] > 0 else None,
                    "gas_equivalent_mean": float(gas_eq.mean()) if gas_eq is not None else None,
                    "fixed_per_year": x.fixed_per_year, "has_boiler": s.boiler is not None,
                    "alternative_cost": float(alternative.sum()) if alternative is not None else None,
                    "saving": float(alternative.sum()) - bought_cost if alternative is not None else None,
                    "has_storage": s.storage is not None and bool(s.storage_kwh)},
        "monthly": monthly,
        "daily": {"start": daily.index[0].isoformat(), **{c: rounded(daily[c], 4) for c in daily.columns}},
    }


def system_page(mode: str, cost: dict, j: dict | None = None, technical: dict | None = None,
                sensitivity: dict | None = None, check: dict | None = None) -> dict:
    """The site's yearly cost, and with the joint sizing the sizes found and each block's value in the system; the
    technical summary (each piece of equipment, the year's energy), the sensitivity of the sizes and the battery
    check."""
    page = {"mode": mode, "costs": cost, "technical": technical}
    if j is not None:
        page["joint"] = {"sizes": j["sizes"], "plan": j["plan"], "notes": j["notes"], "total": j["cost"]["total"],
                         "regime": j["regime"], "battery_max_kwh": j["battery_max_kwh"]}
    if sensitivity is not None:
        page["sensitivity"] = {"table": sensitivity["table"], "step_pct": sensitivity["step_pct"],
                               "regime": sensitivity["regime"]}
    if check is not None:
        page["battery_check"] = {k: check[k] for k in ("joint", "sweep", "same", "objective", "table",
                                                       "battery_life_yr", "pv_life_yr")}
    return page


def effects_page(effects: dict, mode: str) -> dict:
    """With and without each technology: per technology its effect on each line of the yearly cost and on the key
    figures, or why it is not evaluated."""
    keep = ("name", "evaluated", "reason", "also", "costs", "figures", "total_with", "total_without", "difference",
            "invested_with", "invested_without", "extra_investment", "running_saving", "payback_yr", "sizes_without")
    return {x: {**{k: e[k] for k in keep if k in e}, "mode": mode} for x, e in effects.items()}


def results_for_page(run_type: str, battery: dict | None = None, boiler: dict | None = None,
                     summary: dict | None = None, electricity: dict | None = None,
                     storage: dict | None = None, system: dict | None = None, effects: dict | None = None,
                     co2: dict | None = None, heat_pump: dict | None = None) -> dict:
    """Every study's results, and every summary value in one flat list (for the Files tab)."""
    flat = {}
    for key, value in (summary or {}).items():
        if isinstance(value, dict):
            flat.update({k: v for k, v in value.items() if not isinstance(v, (list, dict))})
        elif not isinstance(value, list):
            flat[key] = value
    return clean({"run_type": run_type, "view": "system", "system": system, "effects": effects,
                  "electricity": electricity, "battery": battery, "boiler": boiler, "storage": storage, "co2": co2,
                  "heat_pump": heat_pump,
                  "summary": flat})
