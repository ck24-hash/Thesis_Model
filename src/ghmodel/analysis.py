"""Comparisons between model runs: value of a component, financial analysis against a reference, scenario table."""
import warnings
from dataclasses import replace

import numpy as np
import pandas as pd

from .workflow import run_scenario

# (label, key in Results.k, sign): sign -1 for income, so that every row is a cost and saving = reference - scenario
COST_ITEMS = [
    ("Gas cost", "gas_cost", 1), ("CO2 levy on gas", "levy_cost", 1), ("Electricity purchase", "elec_cost", 1),
    ("Electricity export (- revenue)", "export_rev", -1), ("CHP variable O&M", "chp_vom", 1),
    ("Heat dump + CO2 vent cost", "sink_cost", 1), ("Operating cost (OPEX)", "opex", 1),
    ("Annualised capex + O&M: boiler", "capex_boiler", 1), ("Annualised capex + O&M: storage", "capex_tes", 1),
    ("Annualised capex + O&M: CHP", "capex_chp", 1), ("Total annualised cost", "total_cost", 1),
]


def storage_value(build, data, P, res):
    """Monetary value of the thermal storage.

    Reruns the same scenario without storage (capacity and power 0, everything else unchanged, including whether
    sizes are optimised) and compares it with `res`, the Results of the run with storage.
    Saved by storage = cost without storage - cost with storage (positive = the storage saves money).
    Returns (table, indicators, res_without).
    """
    P0 = replace(P, tes_capacity_MWh=0.0, tes_power_MW_th=0.0, OPTIMISE_TES=False)
    _, res0 = run_scenario(build, data, P0, verbose=False)

    k1, k0 = res.k, res0.k
    s1, s0 = (x.summary.set_index("Indicator").Value for x in (res, res0))
    phys_rows = [  # (label, KPI name, unit)
        ("Gas consumption", "Gas consumption", "MWh/y"), ("Heat dumped", "Heat dumped (rejected)", "MWh/y"),
        ("Grid export", "Grid export", "MWh/y"), ("Direct CO2 (gas)", "Direct CO2 (gas combustion)", "t/y"),
        ("Boiler thermal capacity", "Boiler thermal capacity", "MW"), ("CHP electrical capacity", "CHP electrical capacity", "MW"),
        ("Unserved heat", "Unserved heat", "MWh/y"), ("Unserved CO2", "Unserved CO2", "t/y"),
    ]
    rows = [(lab, sign * k1[key], sign * k0[key], "EUR/y") for lab, key, sign in COST_ITEMS]
    rows += [(lab, s1[kpi], s0[kpi], unit) for lab, kpi, unit in phys_rows]
    table = pd.DataFrame(rows, columns=["Item", "With storage", "Without storage", "Unit"]).set_index("Item")
    table.insert(2, "Saved by storage", table["Without storage"] - table["With storage"])

    # simple payback (no discounting): net investment / net yearly operating benefit
    inv1, inv0 = investments(res, P), investments(res0, P0)
    inv_tes = inv1.Investment.get("Thermal storage", 0.0)
    inv_other_avoided = inv0.Investment.sum() - (inv1.Investment.sum() - inv_tes)   # > 0 only if other sizes are optimised
    net_inv = inv_tes - inv_other_avoided
    benefit = (k0["opex"] - k1["opex"]) - (inv1.FOM.sum() - inv0.FOM.sum())
    payback = net_inv / benefit if benefit > 0 else np.inf
    discharged = s1["Energy discharged from storage"]
    net_saving = k0["total_cost"] - k1["total_cost"]
    tes_cap = k1["tes_cap_final"]

    indicators = pd.DataFrame([
        ("Operating cost saved", k0["opex"] - k1["opex"], "EUR/y"),
        ("Net saving after annualised capex (total cost difference)", net_saving, "EUR/y"),
        ("Storage investment (overnight)", inv_tes, "EUR"),
        ("Avoided investment in other equipment", inv_other_avoided, "EUR"),
        ("Simple payback (no discounting)", payback, "years"),
        ("Operating saving per MWh discharged", (k0["opex"] - k1["opex"]) / discharged if discharged else 0.0, "EUR/MWh"),
        ("Net saving per MWh of storage capacity", net_saving / tes_cap if tes_cap else 0.0, "EUR/MWh/y"),
    ], columns=["Indicator", "Value", "Unit"]).set_index("Indicator")

    if s0["Unserved heat"] > 1e-6 or s0["Unserved CO2"] > 1e-6:
        warnings.warn("Without storage some demand is unserved: the comparison is not like-for-like "
                      "(unserved demand is not included in the total annualised cost).")
    return table, indicators, res0


# ---------------------------------------------------------------------------------------------------------------------
# Financial analysis
# ---------------------------------------------------------------------------------------------------------------------
def investments(res, P):
    """Overnight investment, lifetime and fixed O&M of each piece of equipment in a run (the greenhouse is excluded)."""
    k = res.k
    rows = [
        ("Boiler", k["boiler_cap_final"] * P.boiler_capex_EUR_per_kW_th * 1e3, P.boiler_lifetime_y, P.boiler_fom_frac),
        ("Thermal storage", k["tes_cap_final"] * P.tes_capex_EUR_per_kWh * 1e3, P.tes_lifetime_y, P.tes_fom_frac),
        ("CHP", k["chp_cap_final"] * P.chp_capex_EUR_per_kW_el * 1e3, P.chp_lifetime_y, P.chp_fom_frac),
    ]
    df = pd.DataFrame(rows, columns=["Equipment", "Investment", "Lifetime", "FOM share"]).set_index("Equipment")
    df["FOM"] = df.Investment * df["FOM share"]                    # fixed O&M, EUR/y
    return df[df.Investment > 0]


def _capex_flows(inv, horizon):
    """Investment outflows per year 0..horizon: purchase, replacements at the end of each lifetime inside the
    horizon, and straight-line salvage value (negative outflow) of the last unit at the horizon."""
    f = np.zeros(horizon + 1)
    for invest, life in zip(inv.Investment, inv.Lifetime):
        life = max(1, int(round(life)))
        for y in range(0, horizon, life):
            f[y] += invest
        used = horizon % life
        if used:
            f[horizon] -= invest * (life - used) / life
    return f


def _npv(cf, rate):
    return float(np.sum(cf / (1 + rate) ** np.arange(len(cf))))


def irr(cf, lo=-0.99, hi=10.0):
    """Internal rate of return by bisection; NaN if the NPV does not change sign on [lo, hi]."""
    f_lo, f_hi = _npv(cf, lo), _npv(cf, hi)
    if np.sign(f_lo) == np.sign(f_hi):
        return np.nan
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f_mid = _npv(cf, mid)
        if np.sign(f_mid) == np.sign(f_lo):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _payback(cum):
    """First (interpolated) year where a cumulative cash flow becomes >= 0; NaN if never."""
    if cum[0] >= 0:
        return 0.0
    for y in range(1, len(cum)):
        if cum[y] >= 0:
            return y - 1 + (-cum[y - 1]) / (cum[y] - cum[y - 1])
    return np.nan


def financial_analysis(res, res_ref, P, P_ref=None, name="Scenario", ref_name="Reference", sensitivity=0.2):
    """Investment appraisal of a scenario against a reference run (same data).

    Cash flow of year y = (cost of the reference - cost of the scenario): year 0 holds the additional investment,
    years 1..N the operating saving (incl. export revenue) minus the additional fixed O&M, plus replacements and the
    salvage value at the horizon N = P.project_lifetime_y. Discounted with P.discount_rate.
    Sensitivity: NPV for +/- `sensitivity` on prices and investment, first order (dispatch NOT re-optimised).
    Returns a dict with tables 'investments', 'indicators', 'cash_flows', 'sensitivity'.
    """
    P_ref = P_ref or P
    N, rate = int(P.project_lifetime_y), P.discount_rate
    inv, inv_ref = investments(res, P), investments(res_ref, P_ref)
    k, kr = res.k, res_ref.k
    years = np.arange(N + 1)
    disc = (1 + rate) ** -years

    capex = _capex_flows(inv, N) - _capex_flows(inv_ref, N)           # additional investment flows
    op_saving = kr["opex"] - k["opex"]                                # incl. export revenue
    fom_extra = inv.FOM.sum() - inv_ref.FOM.sum()
    yearly = np.where(years > 0, op_saving - fom_extra, 0.0)
    cf = yearly - capex
    cum, cum_disc = np.cumsum(cf), np.cumsum(cf * disc)

    d_inv = inv.Investment.sum() - inv_ref.Investment.sum()
    net_yearly = op_saving - fom_extra
    if d_inv <= 0:
        simple = 0.0 if net_yearly >= 0 else np.nan
    else:
        simple = d_inv / net_yearly if net_yearly > 0 else np.nan
    # IRR only if the investment pays back (cumulative cash flow > 0 at the horizon); otherwise a root can still
    # exist because of the salvage value in the last year, but it has no economic meaning
    npv, rr = _npv(cf, rate), (irr(cf) if cum[-1] > 0 else np.nan)
    d_em = k["emissions"] - kr["emissions"]
    d_total = k["total_cost"] - kr["total_cost"]

    ind = [
        ("Investment in equipment, " + name, inv.Investment.sum(), "EUR"),
        ("Investment in equipment, " + ref_name, inv_ref.Investment.sum(), "EUR"),
        ("Additional investment", d_inv, "EUR"),
        ("Operating cost saving (incl. export revenue)", op_saving, "EUR/y"),
        ("Additional fixed O&M", fom_extra, "EUR/y"),
        ("Net yearly cash saving", net_yearly, "EUR/y"),
        ("Simple payback", simple, "years"),
        ("Discounted payback", _payback(cum_disc), "years"),
        (f"NPV over {N} years at {100 * rate:.1f} %", npv, "EUR"),
        ("IRR (NaN = does not pay back)", 100 * rr if np.isfinite(rr) else np.nan, "%"),
        ("Total annualised cost, " + name, k["total_cost"], "EUR/y"),
        ("Total annualised cost, " + ref_name, kr["total_cost"], "EUR/y"),
        ("Saving on total annualised cost", -d_total, "EUR/y"),
        ("Saving on total annualised cost (share of reference)", -100 * d_total / kr["total_cost"], "%"),
        ("Export revenue, " + name, k["export_rev"], "EUR/y"),
        ("CO2 emission change (direct + indirect)", d_em, "t/y"),
        ("CO2 abatement cost (if emissions fall; negative = saves money)",
         d_total / -d_em if d_em < -1e-9 else np.nan, "EUR/t"),
        ("Investment per m2 of greenhouse, " + name, inv.Investment.sum() / P.greenhouse_area_m2, "EUR/m2"),
    ]
    indicators = pd.DataFrame(ind, columns=["Indicator", "Value", "Unit"]).set_index("Indicator")
    cash_flows = pd.DataFrame({"Investment flows": -capex, "Operating saving - extra O&M": yearly,
                               "Net cash flow": cf, "Cumulative": cum, "Discounted": cf * disc,
                               "Cumulative discounted": cum_disc}, index=pd.Index(years, name="Year"))

    # first-order sensitivity of the NPV (dispatch kept): NPV change = annuity sum x change of the yearly saving
    ann = disc[1:].sum()
    pv_capex = float(np.sum(capex * disc))
    effects = {   # change of NPV for +100 % of each item
        "Gas price": ann * (kr["gas_cost"] - k["gas_cost"]),
        "Carbon levy": ann * (kr["levy_cost"] - k["levy_cost"]),
        "Electricity import price": ann * (kr["elec_cost"] - k["elec_cost"]),
        "Electricity export price": ann * (k["export_rev"] - kr["export_rev"]),
        "Equipment investment": -pv_capex,
    }
    sens = pd.DataFrame([(item, npv - sensitivity * e, npv + sensitivity * e) for item, e in effects.items()],
                        columns=["Parameter", f"NPV at -{100 * sensitivity:.0f} %", f"NPV at +{100 * sensitivity:.0f} %"]
                        ).set_index("Parameter")
    return dict(investments=inv, investments_ref=inv_ref, indicators=indicators, cash_flows=cash_flows,
                sensitivity=sens, name=name, ref_name=ref_name, npv=npv, irr=rr)


def compare_scenarios(results):
    """Side-by-side KPI table: results = {name: Results}. Same rows for every scenario."""
    cols = {name: res.summary.set_index(["Group", "Indicator"]).Value for name, res in results.items()}
    table = pd.DataFrame(cols)
    table["Unit"] = next(iter(results.values())).summary.set_index(["Group", "Indicator"]).Unit
    return table
