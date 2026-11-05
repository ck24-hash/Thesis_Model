"""The electricity side of every run: where the site's electricity comes from and where the PV goes, self-consumption
and self-sufficiency, and the money to and from the grid. For the system without battery always, and with the
battery's chosen size too when the system has one (the battery study's dispatches are used, nothing is solved again).

Per step (kW), with the site's PV (Voltiris + existing PV, one generator) split by their shares of the step's output:
    PV to load        min(PV, load)
    PV to battery     charging, up to the step's PV surplus
    PV exported       the rest of the PV
    battery to load   discharging, up to the load the PV leaves
    battery to grid   the rest of the discharging (exported)
    grid to load      the rest of the load
    grid to battery   the rest of the charging (bought from the grid)
so that load = PV to load + battery to load + grid to load, PV = PV to load + PV to battery + PV exported, grid
import = grid to load + grid to battery and grid export = PV exported + battery to grid. With a heat pump the load is
the greenhouse load + the heat pump's draw; the heat pump's part is given apart (heat_pump).
Self-consumption and self-sufficiency are the reference model's (flows.sc_ss: PV through the battery counts after its
round-trip loss). The bill by component is flows.bill; the bill without PV (all the load from the grid, the starting
regime) gives what the PV, and the battery, save on the bill.

Savings against the other way of supplying the electricity:
    PV (the system without battery, against all the load bought): imports avoided = PV to load x import price,
        + export revenue, + capacity charges saved, - EaaS fee; they add up to the bill without PV - the bill.
    battery (with it, against without it): imports avoided = battery to load x import price, + its exports, - the
        PV it stored instead of exporting, - the grid energy it bought to charge, + capacity charges saved, + other
        (regime switch, EaaS fee); they add up to the bill without battery - the bill with it.
"""
from __future__ import annotations

import gc

import pandas as pd

from system import dispatch, flows
from system.setup import System

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SPLIT = ["load", "voltiris_to_load", "existing_to_load", "battery_to_load", "grid_to_load", "pv_to_battery",
         "pv_exported"]


def split(res: pd.DataFrame, s: System) -> pd.DataFrame:
    """Where each kW of the step comes from and goes to (the module's docstring)."""
    pv, load = res["pv"], res["load"]
    pv_total = s.pv_total.reindex(res.index)
    volt_share = (s.volt_pv.reindex(res.index) / pv_total).where(pv_total > 0, 0.0)
    if "battery_power" in res.columns:
        charge, discharge = (-res["battery_power"]).clip(lower=0), res["battery_power"].clip(lower=0)
    else:
        charge = discharge = pv * 0.0
    pv_to_load = pv.clip(upper=load)
    pv_to_battery = charge.clip(upper=(pv - load).clip(lower=0))
    battery_to_load = discharge.clip(upper=(load - pv).clip(lower=0))
    return pd.DataFrame({
        "load": load,
        "voltiris_to_load": pv_to_load * volt_share,
        "existing_to_load": pv_to_load * (1 - volt_share),
        "battery_to_load": battery_to_load,
        "grid_to_load": (load - pv_to_load - battery_to_load).clip(lower=0),
        "pv_to_battery": pv_to_battery,
        "pv_exported": (pv - pv_to_load - pv_to_battery).clip(lower=0),
        "battery_to_grid": (discharge - battery_to_load).clip(lower=0),
        "grid_to_battery": (charge - pv_to_battery).clip(lower=0),
        "pv": pv,
        "voltiris": pv * volt_share,
        "existing": pv * (1 - volt_share),
        "battery_soc": res["battery_soc"] if "battery_soc" in res.columns else pv * 0.0,
        "heat_pump": res["heat_pump"] if "heat_pump" in res.columns else pv * 0.0,
    }, index=res.index)


def bill_table(bills: dict) -> pd.DataFrame:
    """The bills by component as one table, one column per bill: import price components, capacity charges, export
    revenue (negative), EaaS fee, total."""
    first = next(iter(bills.values()))
    rows = ([k for k in first if k.startswith("import_")] + [k for k in first if k.startswith("capacity_")])
    names = {k: ("Import, " + k[7:].replace("_", " ") if k.startswith("import_")
                 else "Capacity charge, " + k[9:].replace("_", " ")) for k in rows}
    table = {label: {**{names[k]: b.get(k, 0.0) for k in rows}, "Export revenue": -b["exp_rev"],
                     "EaaS fee": b["eaas_fee"], "Total": b["total"]} for label, b in bills.items()}
    return pd.DataFrame(table)


def case(res: pd.DataFrame, s: System, regime: str, no_pv_regime: str, label: str) -> dict:
    """One dispatch's electricity: key figures, the bill without and with PV, the month by month table, and the
    split per step."""
    dt = s.dt
    sp = split(res, s)
    sc = flows.sc_ss(res, s)
    bill = flows.bill(res["grid_import"], res["grid_export"], s, regime)
    no_pv = flows.bill(res["load"], None, s, no_pv_regime)   # all the load from the grid, the heat pump's too

    def mwh(x):
        return float(x.sum() * dt / 1000)
    kpi = {
        "label": label, "regime": regime, "currency": s.currency,
        "load_mwh": mwh(sp["load"]), "load_peak_kw": float(sp["load"].max()), "heat_pump_mwh": mwh(sp["heat_pump"]),
        "voltiris_mwh": mwh(sp["voltiris"]), "existing_pv_mwh": mwh(sp["existing"]), "pv_mwh": mwh(res["pv"]),
        "voltiris_to_load_mwh": mwh(sp["voltiris_to_load"]), "existing_to_load_mwh": mwh(sp["existing_to_load"]),
        "battery_to_load_mwh": mwh(sp["battery_to_load"]), "grid_to_load_mwh": mwh(sp["grid_to_load"]),
        "pv_to_battery_mwh": mwh(sp["pv_to_battery"]), "pv_exported_mwh": mwh(sp["pv_exported"]),
        "pv_used_on_site_mwh": sc["pv_used_locally"],
        "import_mwh": mwh(res["grid_import"]), "export_mwh": mwh(res["grid_export"]),
        "import_peak_kw": float(res["grid_import"].max()),
        "sc_pct": sc["sc_pct"], "ss_pct": sc["ss_pct"],
        "import_cost": bill["imp_cost"], "capacity_charges": bill["demand"], "export_revenue": bill["exp_rev"],
        "eaas_fee": bill["eaas_fee"], "bill": bill["total"],
        "bill_no_pv": no_pv["total"], "saving_vs_no_pv": no_pv["total"] - bill["total"],
        "saving_on_imports": (no_pv["imp_cost"] + no_pv["demand"]) - (bill["imp_cost"] + bill["demand"]),
    }
    month = flows.monthly_breakdown(res, sc, s, regime)
    sums = sp.groupby(sp.index.month).sum() * dt / 1000
    monthly = pd.DataFrame({
        "Load (MWh)": sums["load"].values,
        "Voltiris to load (MWh)": sums["voltiris_to_load"].values,
        "Existing PV to load (MWh)": sums["existing_to_load"].values,
        "Battery to load (MWh)": sums["battery_to_load"].values,
        "Grid to load (MWh)": sums["grid_to_load"].values,
        "PV to battery (MWh)": sums["pv_to_battery"].values,
        "PV exported (MWh)": sums["pv_exported"].values,
        "Battery to grid (MWh)": sums["battery_to_grid"].values,
        "Grid to battery (MWh)": sums["grid_to_battery"].values,
        **({"Heat pump (MWh)": sums["heat_pump"].values} if "heat_pump" in res.columns else {}),
        "SC (%)": month["SC (%)"].values, "SS (%)": month["SS (%)"].values,
        "Import cost": month["Import cost"].values, "Capacity charge": month["Capacity charge"].values,
        "Export revenue": month["Export rev"].values, "EaaS fee": month["EaaS fee"].values,
    }, index=month.index)
    monthly["Net"] = monthly["Import cost"] + monthly["Capacity charge"] - monthly["Export revenue"] + monthly["EaaS fee"]
    return {"kpi": kpi, "bills": bill_table({"Without PV": no_pv, label: bill}), "monthly": monthly, "split": sp}


def _by_month(x: pd.Series) -> pd.Series:
    return x.groupby(x.index.month).sum().reindex(range(1, 13), fill_value=0.0)


def pv_savings(res: pd.DataFrame, sp: pd.DataFrame, s: System, regime: str) -> dict:
    """What the PV saves against buying all the load from the grid (a dispatch without battery, same regime)."""
    dt, bm, t = s.dt, s.bm, s.grid.tariff
    price = s.import_price(regime).reindex(res.index)
    used = sp["voltiris_to_load"] + sp["existing_to_load"]
    parts = pd.DataFrame({
        "Imports avoided": _by_month(used * price * dt).values,
        "Export revenue": _by_month(bm.grower_export_revenue(res["grid_export"])).values,
        "Capacity charges saved": t.monthly_capacity_charge(res["load"], regime)
                                  - t.monthly_capacity_charge(res["grid_import"], regime),
        "EaaS fee": -_by_month(bm.eaas_fee(res["grid_export"])).values,
    }, index=MONTHS)
    parts["Total"] = parts.sum(axis=1)
    return {"parts": parts.sum().to_dict(), "monthly": parts,
            "figures": {"pv_used_mwh": float(used.sum() * dt / 1000),
                        "pv_exported_mwh": float(sp["pv_exported"].sum() * dt / 1000),
                        "import_price_avoided": float((used * price).sum() / used.sum()) if used.sum() > 0 else None}}


def battery_savings(nb: dict, b: dict, s: System, regime: str) -> dict:
    """What the battery saves on the bill against the same system without it, flow by flow."""
    dt, bm = s.dt, s.bm
    sp = b["split"]
    price = s.import_price(regime).reindex(sp.index)
    parts = pd.DataFrame({
        "Imports avoided": _by_month(sp["battery_to_load"] * price * dt).values,
        "Battery exports": _by_month(bm.grower_export_revenue(sp["battery_to_grid"])).values,
        "PV stored instead of exported": -_by_month(bm.grower_export_revenue(sp["pv_to_battery"])).values,
        "Grid energy bought to charge": -_by_month(sp["grid_to_battery"] * price * dt).values,
        "Capacity charges saved": (nb["monthly"]["Capacity charge"] - b["monthly"]["Capacity charge"]).values,
    }, index=MONTHS)
    total = (nb["monthly"]["Net"] - b["monthly"]["Net"]).values   # the monthly bill, capacity charges included
    parts["Other (regime, EaaS fee)"] = total - parts.sum(axis=1)
    parts["Total"] = total
    delivered = sp["battery_to_load"].sum() * dt / 1000
    stored = (sp["pv_to_battery"] + sp["grid_to_battery"]).sum() * dt / 1000
    totals = parts.sum()
    return {"parts": totals.to_dict(), "monthly": parts,
            "figures": {"to_load_mwh": float(delivered), "to_grid_mwh": float(sp["battery_to_grid"].sum() * dt / 1000),
                        "from_pv_mwh": float(sp["pv_to_battery"].sum() * dt / 1000),
                        "from_grid_mwh": float(sp["grid_to_battery"].sum() * dt / 1000),
                        "price_avoided": totals["Imports avoided"] / (delivered * 1000) if delivered > 0 else None,
                        "cost_stored": -(totals["PV stored instead of exported"] + totals["Grid energy bought to charge"])
                        / (stored * 1000) if stored > 0 else None}}


def run(s: System, *, regime_auto: bool = True, regime_manual: str | None = None, battery: dict | None = None,
        res_no_battery: pd.DataFrame | None = None, regime: str | None = None, log=print) -> dict:
    """The electricity of the run's system (the heat blocks at their chosen sizes): without battery, and with the
    battery study's chosen size when there is one. battery: that study's results (dispatch, dispatch_no_battery,
    summary); res_no_battery: a dispatch without battery already solved, under `regime`; else it is solved. The
    regime without battery is the battery study's, else `regime`, else the starting one."""
    base, _ = dispatch.choose_regime(s, regime_auto, regime_manual)
    if battery:
        base = battery["summary"].get("regime_no_battery") or base
    elif regime is not None:
        base = regime
    log("\n=== ELECTRICITY ===")
    res_nb = battery.get("dispatch_no_battery") if battery else res_no_battery
    if res_nb is None:
        log("  Solving the year for the electricity side ...")
        n = dispatch.solve(s, base)
        if n is None:
            raise RuntimeError("The year could not be solved.")
        res_nb = dispatch.results(n, s)
        del n
        gc.collect()
    cases = {"no_battery": case(res_nb, s, base, base, "Without battery" if battery else "The system")}
    cases["no_battery"]["pv_savings"] = pv_savings(res_nb, cases["no_battery"]["split"], s, base)
    if battery:
        sm = battery["summary"]
        cases["battery"] = case(battery["dispatch"], s, sm["regime_battery"], base,
                                f"With {sm['battery_kwh']:,.0f} kWh battery")
        cases["battery"]["battery_savings"] = battery_savings(cases["no_battery"], cases["battery"], s,
                                                              sm["regime_battery"])
    final = cases["battery" if battery else "no_battery"]["kpi"]
    log(f"  PV {final['pv_mwh']:,.0f} MWh, self-consumption {final['sc_pct']:.1f} %, self-sufficiency "
        f"{final['ss_pct']:.1f} %, bill {final['bill']:,.0f}/yr (without PV {final['bill_no_pv']:,.0f})")
    summary = {"el_" + k: v for k, v in final.items() if k not in ("label", "currency")}
    return {"summary": summary, "cases": cases}
