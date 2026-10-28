"""What a dispatch means (from elements/battery_reference engine/flows.py): self-consumption and self-sufficiency, the yearly bill, the monthly table, and how the
battery's value splits into self-consumption, arbitrage and peak shaving."""
from __future__ import annotations

import pandas as pd

from system.setup import System

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def sc_ss(res: pd.DataFrame, s: System) -> dict:
    """Self-consumption (share of PV used on site) and self-sufficiency (share of load met by PV), in %.
    PV that passes through the battery counts after the round-trip loss; grid energy stored is not self-supplied."""
    dt, eta2 = s.dt, s.eta2
    pv_ = res["pv"] * dt
    load_ = res["load"] * dt
    total_pv = pv_.sum() / 1000
    total_load = load_.sum() / 1000
    pv_surplus = (pv_ - load_).clip(lower=0)
    pv_direct = pv_.clip(upper=load_)
    pv_direct_mwh = pv_direct.sum() / 1000
    if "battery_power" in res.columns:
        bat_discharge = res["battery_power"].clip(lower=0) * dt
        bat_charge = (-res["battery_power"]).clip(lower=0) * dt
        bat_from_pv = pv_surplus.clip(upper=bat_charge)
        pv_into_bat_mwh = bat_from_pv.sum() / 1000
        bat_to_load = bat_discharge.clip(upper=(load_ - pv_).clip(lower=0))
        frac_fp = bat_from_pv.sum() / bat_charge.sum() if bat_charge.sum() > 0 else 0.0
        pv_stored_self = min(bat_to_load.sum() / 1000 * frac_fp, pv_into_bat_mwh * eta2, pv_into_bat_mwh)
        pv_stored_sold = max(pv_into_bat_mwh - pv_stored_self, 0.0)
        pv_surplus_grid = max(pv_surplus.sum() / 1000 - pv_into_bat_mwh, 0.0)
    else:
        bat_from_pv = pd.Series(0.0, index=res.index)
        pv_into_bat_mwh = pv_stored_self = pv_stored_sold = 0.0
        pv_surplus_grid = pv_surplus.sum() / 1000
    pv_used_locally = pv_direct_mwh + pv_stored_self
    return dict(
        sc_pct=pv_used_locally / total_pv * 100 if total_pv > 0 else 0.0,
        ss_pct=pv_used_locally / total_load * 100 if total_load > 0 else 0.0,
        pv_direct=pv_direct, bat_from_pv=bat_from_pv, pv_direct_mwh=pv_direct_mwh,
        pv_into_bat_mwh=pv_into_bat_mwh, pv_stored_self=pv_stored_self, pv_stored_sold=pv_stored_sold,
        pv_surplus_grid=pv_surplus_grid, pv_used_locally=pv_used_locally,
        total_pv=total_pv, total_load=total_load,
    )


def economics(res: pd.DataFrame, s: System, regime: str) -> dict:
    """The year's bill under one regime: import cost, export revenue, EaaS fee, capacity charges (demand_annual)."""
    dt = s.dt
    imp_cost = (res["grid_import"] * s.import_price(regime) * dt).sum()
    exp_rev = s.bm.grower_export_revenue(res["grid_export"]).sum()
    eaas_fee = s.bm.eaas_fee(res["grid_export"]).sum()
    main = s.grid.tariff.main_monthly_charge
    window = s.grid.tariff.window_mask(main["window"] if main else "all", res.index)
    demand = s.grid.tariff.yearly_capacity_charge(res["grid_import"], regime)
    return dict(
        import_mwh=(res["grid_import"] * dt).sum() / 1000,
        export_mwh=(res["grid_export"] * dt).sum() / 1000,
        import_cost=imp_cost, exp_rev=exp_rev, eaas_fee=eaas_fee,
        net_cost=imp_cost - exp_rev + eaas_fee,
        peak_hp_kw=res["grid_import"][window].max(),
        demand_annual=demand,
        total_cost=imp_cost - exp_rev + eaas_fee + demand,
    )


def bill(import_kw: pd.Series, export_kw: pd.Series | None, s: System, regime: str, volt: bool = True) -> dict:
    """The year's bill by component (as an invoice), with exports and the EaaS fee. volt=False: no Voltiris."""
    da = s.grid.da.reindex(import_kw.index) if s.grid.da is not None else None
    out = s.grid.tariff.import_cost_breakdown(import_kw, regime, s.dt, da)
    exp_rev = s.bm.grower_export_revenue(export_kw, volt).sum() if export_kw is not None else 0.0
    fee = s.bm.eaas_fee(export_kw, volt).sum() if export_kw is not None else 0.0
    out.update(exp_rev=exp_rev, eaas_fee=fee, total=out["imp_cost"] + out["demand"] - exp_rev + fee)
    return out


def monthly_breakdown(res: pd.DataFrame, flows: dict, s: System, regime: str) -> pd.DataFrame:
    """Per month: import, export, costs, PV used directly, through the battery or sold, SC, SS, the billed peak of the
    main monthly charge and the capacity charges (yearly charges spread as 1/12)."""
    dt, eta2 = s.dt, s.eta2
    has_bat = "battery_power" in res.columns
    main = s.grid.tariff.main_monthly_charge
    peaks = (s.grid.tariff.billed_peaks(main, res["grid_import"]) if main
             else res["grid_import"].groupby(res.index.month).max().reindex(range(1, 13), fill_value=0.0))
    charges = s.grid.tariff.monthly_capacity_charge(res["grid_import"], regime)
    price = s.import_price(regime)
    exp_rev_ts = s.bm.grower_export_revenue(res["grid_export"])
    fee_ts = s.bm.eaas_fee(res["grid_export"])
    rows = []
    for m in range(1, 13):
        mask = res.index.month == m
        r = res[mask]
        imp_kwh = r["grid_import"] * dt
        exp_kwh = r["grid_export"] * dt
        pv_m = (r["pv"] * dt).sum() / 1000
        ld_m = (r["load"] * dt).sum() / 1000
        pv_dir_m = flows["pv_direct"][mask].sum() / 1000
        bat_fp_m = flows["bat_from_pv"][mask].sum() / 1000
        if has_bat:
            bat_chg_m = ((-r["battery_power"]).clip(lower=0) * dt).sum() / 1000
            bat_dis_m = (r["battery_power"].clip(lower=0) * dt).sum() / 1000
            pv_sur_m = (r["pv"] * dt - r["load"] * dt).clip(lower=0).sum() / 1000
            bat_tl_m = (r["battery_power"].clip(lower=0) * dt).clip(
                upper=(r["load"] - r["pv"]).clip(lower=0) * dt).sum() / 1000
            frac_m = bat_fp_m / bat_chg_m if bat_chg_m > 0 else 0.0
            pv_st_s_m = min(bat_tl_m * frac_m, bat_fp_m * eta2, bat_fp_m)
            pv_st_x_m = max(bat_fp_m - pv_st_s_m, 0.0)
            pv_sold_m = max(pv_sur_m - bat_fp_m, 0.0)
        else:
            bat_chg_m = bat_dis_m = pv_st_s_m = pv_st_x_m = 0.0
            pv_sold_m = pv_m - pv_dir_m
        pv_used_m = pv_dir_m + pv_st_s_m
        imp_cost = (imp_kwh * price[mask]).sum()
        row = {
            "Import (MWh)": imp_kwh.sum() / 1000,
            "Export (MWh)": exp_kwh.sum() / 1000,
            "Import cost": imp_cost,
            "Export rev": exp_rev_ts[mask].sum(),
            "EaaS fee": fee_ts[mask].sum(),
            "Net cost": imp_cost - exp_rev_ts[mask].sum() + fee_ts[mask].sum(),
            "PV direct (MWh)": pv_dir_m,
            "PV stored+selfcons (MWh)": pv_st_s_m,
            "PV stored+sold (MWh)": pv_st_x_m,
            "PV sold direct (MWh)": pv_sold_m,
            "SC (%)": pv_used_m / pv_m * 100 if pv_m > 0 else 0.0,
            "SS (%)": pv_used_m / ld_m * 100 if ld_m > 0 else 0.0,
            "Billed peak (kW)": float(peaks.loc[m]),
            "Capacity charge": float(charges[m - 1]),
        }
        if has_bat:
            row["Bat charge (MWh)"] = bat_chg_m
            row["Bat discharge (MWh)"] = bat_dis_m
        rows.append(row)
    return pd.DataFrame(rows, index=MONTHS)


def value_split(res: pd.DataFrame, s: System, regime: str, energy_savings: float) -> tuple[float, float]:
    """Split the battery's energy value into self-consumption (charged from PV surplus that would have been
    exported) and arbitrage (charged from the grid at a cheaper step), with a per-month spread estimate, then
    scaled so the two add up to the LP's energy value exactly."""
    dt, eta2 = s.dt, s.eta2
    price = s.import_price(regime)
    export_value = s.bm.export_value
    pv_sur = (res["pv"] - res["load"]).clip(lower=0)
    chg = (-res["battery_power"]).clip(lower=0)
    dis = res["battery_power"].clip(lower=0)
    chg_pv = chg.clip(upper=pv_sur)
    chg_grid = (chg - chg_pv).clip(lower=0)
    sc_raw = arb_raw = 0.0
    for mo in range(1, 13):
        mask = res.index.month == mo
        ip_m, dis_m, cpv_m, cgr_m = price[mask], dis[mask], chg_pv[mask], chg_grid[mask]
        avg_dis_price = (dis_m * ip_m).sum() / dis_m.sum() if dis_m.sum() > 0 else ip_m.mean()
        if cpv_m.sum() > 0:
            ev_pv = (cpv_m * export_value[mask]).sum() / cpv_m.sum()
            sc_raw += cpv_m.sum() * dt * (avg_dis_price * eta2 - ev_pv)
        if cgr_m.sum() > 0:
            avg_chg_price = (cgr_m * ip_m).sum() / cgr_m.sum()
            arb_raw += cgr_m.sum() * dt * (avg_dis_price * eta2 - avg_chg_price / eta2)
    raw = sc_raw + arb_raw
    scale = energy_savings / raw if raw != 0 else 0.0
    return sc_raw * scale, arb_raw * scale
