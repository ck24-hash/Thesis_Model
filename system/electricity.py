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
import = grid to load + grid to battery and grid export = PV exported + battery to grid.
Self-consumption and self-sufficiency are the reference model's (flows.sc_ss: PV through the battery counts after its
round-trip loss). The bill by component is flows.bill; the bill without PV (all the load from the grid, the starting
regime) gives what the PV, and the battery, save on the bill.
"""
from __future__ import annotations

import gc

import pandas as pd

from system import dispatch, flows
from system.setup import System

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
    no_pv = flows.bill(s.load, None, s, no_pv_regime)

    def mwh(x):
        return float(x.sum() * dt / 1000)
    kpi = {
        "label": label, "regime": regime, "currency": s.currency,
        "load_mwh": mwh(sp["load"]), "load_peak_kw": float(sp["load"].max()),
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
        "SC (%)": month["SC (%)"].values, "SS (%)": month["SS (%)"].values,
        "Import cost": month["Import cost"].values, "Capacity charge": month["Capacity charge"].values,
        "Export revenue": month["Export rev"].values, "EaaS fee": month["EaaS fee"].values,
    }, index=month.index)
    monthly["Net"] = monthly["Import cost"] + monthly["Capacity charge"] - monthly["Export revenue"] + monthly["EaaS fee"]
    return {"kpi": kpi, "bills": bill_table({"Without PV": no_pv, label: bill}), "monthly": monthly, "split": sp}


def run(s: System, *, regime_auto: bool = True, regime_manual: str | None = None, battery: dict | None = None,
        res_no_battery: pd.DataFrame | None = None, log=print) -> dict:
    """The electricity of the run's system (the heat blocks at their chosen sizes): without battery, and with the
    battery study's chosen size when there is one. battery: that study's results (dispatch, dispatch_no_battery,
    summary); res_no_battery: a dispatch without battery already solved; else it is solved."""
    base, _ = dispatch.choose_regime(s, regime_auto, regime_manual)
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
    if battery:
        sm = battery["summary"]
        cases["battery"] = case(battery["dispatch"], s, sm["regime_battery"], base,
                                f"With {sm['battery_kwh']:,.0f} kWh battery")
    final = cases["battery" if battery else "no_battery"]["kpi"]
    log(f"  PV {final['pv_mwh']:,.0f} MWh, self-consumption {final['sc_pct']:.1f} %, self-sufficiency "
        f"{final['ss_pct']:.1f} %, bill {final['bill']:,.0f}/yr (without PV {final['bill_no_pv']:,.0f})")
    summary = {"el_" + k: v for k, v in final.items() if k not in ("label", "currency")}
    return {"summary": summary, "cases": cases}
