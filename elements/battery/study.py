"""The battery study: the battery block on its own, sized with the rest of the system fixed (from
elements/battery_reference engine/pipeline.py and blocks/finance.py), in the reference model's order:

1. the regime from the site's DUP (no battery), and the subsidised maximum size;
2. the no-battery year (PV only), its bill and SC/SS;
3. the size sweep and the chosen size;
4. the chosen size's year under its regime, its bill, SC/SS and value split;
5. Voltiris's own saving, battery cost over the PV life (with the EMS capex), and the payback table.

Returns a summary dict (the reference model's summary keys) and the tables behind it.
"""
from __future__ import annotations

import gc

import pandas as pd

from common.money import payback_years
from elements.battery import sizing
from system import dispatch, flows
from system.setup import System


def choose_regime(s: System, auto: bool = True, manual: str | None = None) -> tuple[str, float | None]:
    """The no-battery regime: from the DUP of what is drawn from the grid with all PV and no battery."""
    return s.grid.choose_regime((s.load - s.pv_total).clip(lower=0), auto, manual)


def payback_rows(*, eaas: bool, pv_modules: int, eaas_price_per_mwh: float | None,
                 pv_capex: float, pv_capex_net: float, battery_capex_no_sub: float, battery_capex_sub: float,
                 pv_saving: float, battery_saving: float, pv_label: str, battery_label: str,
                 pv_life_yr: float, currency: str = "CHF") -> list[dict]:
    """One row per scenario: capex over the PV life, saving per year, payback, and whether it pays back in time.
    Capex = Voltiris + battery first purchase (with the EMS capex) + battery replacements (unsubsidised)."""
    if eaas:   # Voltiris owns the modules: the grower pays the EaaS fee (inside pv_saving), no capex
        rows = [(f"Voltiris EaaS only ({eaas_price_per_mwh:,.0f} {currency}/MWh, no capex)", 0.0, pv_saving),
                ("Voltiris EaaS + battery (no sub)", battery_capex_no_sub, pv_saving + battery_saving),
                (f"Voltiris EaaS + battery (bat sub {battery_label})", battery_capex_sub, pv_saving + battery_saving)]
    elif pv_modules > 0:
        rows = [("Voltiris only (no sub)", pv_capex, pv_saving),
                ("Voltiris + battery (no sub)", pv_capex + battery_capex_no_sub, pv_saving + battery_saving)]
        if pv_capex_net != pv_capex:
            rows.append((f"Voltiris only (PV sub {pv_label})", pv_capex_net, pv_saving))
        rows.append((f"Voltiris + battery (PV sub {pv_label}, bat sub {battery_label})",
                     pv_capex_net + battery_capex_sub, pv_saving + battery_saving))
    else:
        rows = [("Battery (no sub)", battery_capex_no_sub, battery_saving),
                (f"Battery (sub {battery_label}, 1st purchase)", battery_capex_sub, battery_saving)]
    out = []
    for name, cap, sav in rows:
        pb = payback_years(cap, sav)
        out.append({"scenario": name, "capex": cap, "saving_per_year": sav, "payback_yr": pb,
                    "viable": pb <= pv_life_yr})
    return out


def run(s: System, *, regime_auto: bool = True, regime_manual: str | None = None,
        sizing_settings: dict | None = None, tag: str = "case", log=print) -> dict:
    if s.battery is None:
        raise ValueError("The battery study needs a battery block in the system.")
    dt, t, b = s.dt, s.grid.tariff, s.battery
    cfg = {**sizing.DEFAULTS, **(sizing_settings or {})}

    # 1. regime and subsidised maximum
    base, dup_no_battery = choose_regime(s, regime_auto, regime_manual)
    if dup_no_battery is not None:
        log(f"  Auto DUP = {dup_no_battery:,.0f} h  ->  regime {base}")
    else:
        log(f"  Regime {base}")
    if b.cap_sweep_at_subsidy:
        log(f"  Subsidy max size : {b.subsidy_threshold_kwh:,.0f} kWh")

    # 2. no battery
    log("  Solving the year without battery ...")
    n_nb = dispatch.solve(s, base)
    if n_nb is None:
        raise RuntimeError("The no-battery optimisation failed.")
    res_nb = dispatch.results(n_nb, s)
    del n_nb
    gc.collect()
    e_nb = flows.economics(res_nb, s, base)
    sc_nb = flows.sc_ss(res_nb, s)
    monthly_nb = flows.monthly_breakdown(res_nb, sc_nb, s, base)
    baseline_cost = (s.load * s.import_price(base) * dt).sum()
    baseline_demand = t.yearly_capacity_charge(s.load, base)
    baseline_op_cost = e_nb["total_cost"]

    # 3. sizing
    log("\n=== BATTERY SIZING SWEEP ===")
    solved: dict = {}   # every size's dispatch from the sweep, so the chosen size is not solved again
    table = sizing.sweep(s, base, baseline_op_cost, cfg, log=log, dispatches=solved)
    size = sizing.choose(table, cfg["objective"], cfg["custom_kwh"], b.life_yr)
    regime = table.loc[size, "regime"]
    dup_lock = table.loc[size, "dup_lock"] or None
    log(f"\n  Chosen: {size} kWh, regime {regime}" + ("  (DUP held by constraint)" if dup_lock else ""))

    # 4. the chosen size: its dispatch from the sweep (the same solve), or solved again if it is missing
    res_b = solved.get((size, regime, dup_lock or ""))
    if res_b is None:
        n_b = dispatch.solve(s, regime, battery_kwh=size, dup_lock=dup_lock)
        if n_b is None:
            raise RuntimeError(f"The optimisation with {size} kWh failed.")
        res_b = dispatch.results(n_b, s)
        del n_b
    solved.clear()
    gc.collect()
    e_b = flows.economics(res_b, s, regime)
    sc_b = flows.sc_ss(res_b, s)
    monthly_b = flows.monthly_breakdown(res_b, sc_b, s, regime)

    gross = b.gross(size)
    net_capex = b.net_capex(size)
    baseline_annual_net = (s.bm.pv_net_revenue(res_nb["grid_export"])
                           - res_nb["grid_import"] * s.import_price(base) * dt).sum()
    annual_net_bat = (s.bm.pv_net_revenue(res_b["grid_export"]).sum()
                      - (res_b["grid_import"] * s.import_price(regime) * dt).sum())
    regime_switch = ((res_b["grid_import"] * (s.import_price(base) - s.import_price(regime)) * dt).sum()
                     if regime != base else 0.0)
    energy_savings = annual_net_bat - baseline_annual_net - regime_switch
    sc_saving, arb_saving = flows.value_split(res_b, s, regime, energy_savings)
    peak_demand = e_nb["demand_annual"] - e_b["demand_annual"]
    peak_shaving = peak_demand + regime_switch
    ancillary = b.ancillary_revenue(size)
    ems = b.ems.fees(ancillary, energy_savings + peak_shaving)
    net_savings = energy_savings + peak_shaving + ancillary - ems["total"]
    investment = net_capex + b.ems.capex
    payback = payback_years(investment, net_savings)
    cycles = (res_b["battery_power"].clip(lower=0).abs() * dt).sum() / size

    # 5. Voltiris saving, cost over the PV life, payback table
    life_pv, life_bat = s.pv_life_yr, b.life_yr
    pv_capex = 0.0 if s.bm.eaas or s.voltiris is None else s.voltiris.gross_capex()
    existing = s.existing if s.existing is not None else pd.Series(0.0, index=s.index)
    imp_exist = (s.load - existing).clip(lower=0)
    exp_exist = (existing - s.load).clip(lower=0)
    dup_exist = t.dup(imp_exist, s.grid.hp_mask, dt)
    regime_exist = t.regime_of(dup_exist) if t.rule else base   # FR: the TURPE option the case chose
    bill_exist = flows.bill(imp_exist, exp_exist, s, regime_exist, volt=False)["total"]
    pv_saving = bill_exist - e_nb["total_cost"] if s.modules > 0 else 0.0
    bat_saving = e_nb["total_cost"] - e_b["total_cost"] + ancillary - ems["total"]
    pv_capex_net = s.voltiris.net_capex(pv_capex) if s.voltiris else 0.0
    repl = b.replacement_cost(size, life_pv)
    bat_no_sub = gross + repl + b.ems.capex
    bat_sub = net_capex + repl + b.ems.capex
    cur = t.currency
    payback_table = payback_rows(
        eaas=s.bm.eaas, pv_modules=s.modules, eaas_price_per_mwh=s.bm.price_per_mwh,
        pv_capex=pv_capex, pv_capex_net=pv_capex_net, battery_capex_no_sub=bat_no_sub, battery_capex_sub=bat_sub,
        pv_saving=pv_saving, battery_saving=bat_saving,
        pv_label=s.voltiris.subsidy_label(cur) if s.voltiris else "",
        battery_label=b.subsidy_label(cur),
        pv_life_yr=life_pv, currency=cur)

    volt_mwh = (s.volt_pv * dt).sum() / 1000
    volt_onsite_nb = (s.bm.volt_share * (s.pv_total - res_nb["grid_export"]).clip(lower=0) * dt).sum() / 1000
    volt_onsite_b = (s.bm.volt_share * (s.pv_total - res_b["grid_export"]).clip(lower=0) * dt).sum() / 1000

    summary = {
        "site_tag": tag, "pv_modules": s.modules,
        "voltiris_model": "none" if s.modules == 0 else s.bm.type,
        "currency": cur, "country": t.p.get("country"), "region": t.p.get("region"), "utility": t.p.get("utility"),
        "eaas_price_per_mwh": s.bm.price_per_mwh if s.bm.eaas else None,
        "regime_no_battery": base, "regime_battery": regime,
        "battery_kwh": size, "battery_net_capex": net_capex, "ems_capex": b.ems.capex,
        "battery_investment": investment, "battery_capex_pv_life": bat_sub,
        "battery_value_yr": net_savings, "battery_energy_savings_yr": energy_savings,
        "battery_sc_saving_yr": sc_saving, "battery_arbitrage_yr": arb_saving,
        "battery_peak_shaving_yr": peak_shaving, "battery_peak_demand_yr": peak_demand,
        "battery_regime_switch_yr": regime_switch, "battery_ancillary_yr": ancillary, "battery_ems_yr": ems["total"],
        "ems_fixed_yr": ems["fixed"],
        "ems_fee_ancillary_voltiris_yr": ems["ancillary_voltiris"], "ems_fee_ancillary_external_yr": ems["ancillary_external"],
        "ems_fee_savings_voltiris_yr": ems["savings_voltiris"], "ems_fee_savings_external_yr": ems["savings_external"],
        "ems_fees_voltiris_yr": ems["voltiris"], "ems_fees_external_yr": ems["external"],
        "battery_payback_yr": payback, "battery_lifetime_profit": net_savings * life_bat - investment,
        "battery_export": s.battery_export,
        "battery_grid_charge_mwh": (res_b["battery_charge_from_grid"].sum() * dt / 1000
                                    if "battery_charge_from_grid" in res_b else None),
        "battery_cycles": cycles,
        "sc_no_battery": sc_nb["sc_pct"], "sc_battery": sc_b["sc_pct"],
        "ss_no_battery": sc_nb["ss_pct"], "ss_battery": sc_b["ss_pct"],
        "voltiris_mwh": volt_mwh, "voltiris_onsite_mwh_no_battery": volt_onsite_nb,
        "voltiris_onsite_mwh_battery": volt_onsite_b,
        "eaas_fee_no_battery": e_nb["eaas_fee"], "eaas_fee_battery": e_b["eaas_fee"],
        "voltiris_capex_grower": pv_capex, "voltiris_saving_yr": pv_saving,
        "bill_existing_pv_only": bill_exist,
        "bill_no_battery": e_nb["total_cost"], "bill_battery": e_b["total_cost"],
        "import_mwh_no_battery": e_nb["import_mwh"], "import_mwh_battery": e_b["import_mwh"],
        "export_mwh_no_battery": e_nb["export_mwh"], "export_mwh_battery": e_b["export_mwh"],
        "pv_life_yr": life_pv,
        "sweep": table.reset_index()[["size", "bat_value", "payback", "lifetime_profit", "regime"]].to_dict("records"),
    }
    bills = pd.DataFrame({
        "No PV": flows.bill(s.load, None, s, base),
        "PV only": flows.bill(res_nb["grid_import"], res_nb["grid_export"], s, base),
        f"PV + {size} kWh": flows.bill(res_b["grid_import"], res_b["grid_export"], s, regime),
    })
    return {
        "summary": summary,
        "sweep": table,
        "monthly_no_battery": monthly_nb,
        "monthly_battery": monthly_b,
        "bills": bills,
        "payback": pd.DataFrame(payback_table),
        "dispatch": res_b,
        "baseline": {"cost_no_pv": baseline_cost, "demand_no_pv": baseline_demand, "dup_no_battery": dup_no_battery},
    }
