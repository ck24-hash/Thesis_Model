"""Payback, lifetime profit and the investment payback table."""
from __future__ import annotations


def payback_years(net_capex: float, saving_per_year: float) -> float:
    return net_capex / saving_per_year if saving_per_year > 0 else float("inf")


def lifetime_profit(saving_per_year: float, life_yr: float, net_capex: float) -> float:
    return saving_per_year * life_yr - net_capex


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
