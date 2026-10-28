"""One study from start to end, in the notebook's order:

1. the regime from the site's DUP (no battery), and the subsidised maximum size;
2. the no-battery year (PV only), its bill and SC/SS;
3. the size sweep and the chosen size;
4. the chosen size's year under its regime, its bill, SC/SS and value split;
5. Voltiris's own saving, battery cost over the PV life (with the EMS capex), and the payback table.

Returns a summary dict (the same keys as the notebook's summary_<tag>.json) and the tables behind it.
"""
from __future__ import annotations

import gc

import pandas as pd

from blocks import capex as capex_block
from blocks import finance
from blocks import subsidies as subsidies_block
from engine import dispatch, flows, sizing
from engine.setup import Setup


def choose_regime(s: Setup, auto: bool = True, manual: str | None = None) -> tuple[str, float | None]:
    """The no-battery regime: from the DUP of what is drawn from the grid with all PV and no battery."""
    if not auto or not s.tariff.rule:
        return manual or s.tariff.regime_names[0], None
    grid_draw = (s.study.load - s.study.pv_total).clip(lower=0)
    dup = s.tariff.dup(grid_draw, s.hp_mask, s.dt)
    return s.tariff.regime_of(dup), dup


def run(s: Setup, *, regime_auto: bool = True, regime_manual: str | None = None,
        sizing_settings: dict | None = None, tag: str = "case", log=print) -> dict:
    st, dt, t = s.study, s.dt, s.tariff
    cfg = {**sizing.DEFAULTS, **(sizing_settings or {})}

    # 1. regime and subsidised maximum
    base, dup_no_battery = choose_regime(s, regime_auto, regime_manual)
    if dup_no_battery is not None:
        log(f"  Auto DUP = {dup_no_battery:,.0f} h  ->  regime {base}")
    else:
        log(f"  Regime {base}")
    if s.cap_sweep_at_subsidy:
        log(f"  Subsidy max size : {s.subsidy_threshold_kwh:,.0f} kWh")

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
    baseline_cost = (st.load * s.import_price(base) * dt).sum()
    baseline_demand = t.yearly_capacity_charge(st.load, base)
    baseline_op_cost = e_nb["total_cost"]

    # 3. sizing
    log("\n=== BATTERY SIZING SWEEP ===")
    solved: dict = {}   # every size's dispatch from the sweep, so the chosen size is not solved again
    table = sizing.sweep(s, base, baseline_op_cost, cfg, log=log, dispatches=solved)
    size = sizing.choose(table, cfg["objective"], cfg["custom_kwh"], s.finance["battery_life_yr"])
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

    gross = capex_block.battery_gross(size, s.capex)
    net_capex = s.battery_net_capex(size)
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
    ancillary = s.ancillary_revenue(size)
    ems = s.ems.fees(ancillary, energy_savings + peak_shaving)
    net_savings = energy_savings + peak_shaving + ancillary - ems["total"]
    investment = net_capex + s.ems.capex
    payback = finance.payback_years(investment, net_savings)
    cycles = (res_b["battery_power"].clip(lower=0).abs() * dt).sum() / size

    # 5. Voltiris saving, cost over the PV life, payback table
    life_pv, life_bat = s.finance["pv_life_yr"], s.finance["battery_life_yr"]
    pv_capex = 0.0 if s.bm.eaas else capex_block.pv_gross(st.modules, s.module_wp, s.capex)
    existing = st.existing_pv if st.existing_pv is not None else pd.Series(0.0, index=st.index)
    imp_exist = (st.load - existing).clip(lower=0)
    exp_exist = (existing - st.load).clip(lower=0)
    dup_exist = t.dup(imp_exist, s.hp_mask, dt)
    regime_exist = t.regime_of(dup_exist) if t.rule else base   # FR: the TURPE option the case chose
    bill_exist = flows.bill(imp_exist, exp_exist, s, regime_exist, volt=False)["total"]
    pv_saving = bill_exist - e_nb["total_cost"] if st.modules > 0 else 0.0
    bat_saving = e_nb["total_cost"] - e_b["total_cost"] + ancillary - ems["total"]
    pv_capex_net = subsidies_block.pv_net(pv_capex, st.modules, s.module_wp, s.capex, s.subsidies)
    repl = capex_block.battery_replacement_cost(size, s.capex, life_pv, life_bat)
    bat_no_sub = gross + repl + s.ems.capex
    bat_sub = net_capex + repl + s.ems.capex
    cur = t.currency
    payback_table = finance.payback_rows(
        eaas=s.bm.eaas, pv_modules=st.modules, eaas_price_per_mwh=s.bm.price_per_mwh,
        pv_capex=pv_capex, pv_capex_net=pv_capex_net, battery_capex_no_sub=bat_no_sub, battery_capex_sub=bat_sub,
        pv_saving=pv_saving, battery_saving=bat_saving,
        pv_label=subsidies_block.pv_label(s.subsidies, st.modules, cur),
        battery_label=subsidies_block.battery_label(s.subsidies, s.subsidy_threshold_kwh, cur),
        pv_life_yr=life_pv, currency=cur)

    volt_mwh = (st.volt_pv * dt).sum() / 1000
    volt_onsite_nb = (s.bm.volt_share * (st.pv_total - res_nb["grid_export"]).clip(lower=0) * dt).sum() / 1000
    volt_onsite_b = (s.bm.volt_share * (st.pv_total - res_b["grid_export"]).clip(lower=0) * dt).sum() / 1000

    summary = {
        "site_tag": tag, "pv_modules": st.modules,
        "voltiris_model": "none" if st.modules == 0 else s.bm.type,
        "currency": cur, "country": t.p.get("country"), "region": t.p.get("region"), "utility": t.p.get("utility"),
        "eaas_price_per_mwh": s.bm.price_per_mwh if s.bm.eaas else None,
        "regime_no_battery": base, "regime_battery": regime,
        "battery_kwh": size, "battery_net_capex": net_capex, "ems_capex": s.ems.capex,
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
        "No PV": flows.bill(st.load, None, s, base),
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
