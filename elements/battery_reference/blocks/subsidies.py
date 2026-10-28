"""Subsidies on the battery and the PV: percent, fixed amount, or percent up to a threshold size."""
from __future__ import annotations

from blocks import capex as capex_block


def apply_subsidy(gross: float, mode: str, frac: float, amount: float,
                  size: float | None = None, threshold: float | None = None,
                  cost_at_threshold: float | None = None) -> float:
    """The net price after the subsidy.
    percent:   gross x (1 - frac)
    fixed:     gross - amount, at least 0
    threshold: frac up to `threshold` (in `size`'s units); above it the discount is capped at
               frac x cost_at_threshold, so everything past the threshold is paid in full."""
    if mode == "fixed":
        return max(gross - amount, 0.0)
    if mode == "threshold" and size is not None and threshold is not None and size > threshold:
        return max(gross - frac * cost_at_threshold, 0.0)
    return gross * (1 - frac)


def label(mode: str, frac: float, amount: float, currency: str = "CHF", threshold: float | None = None) -> str:
    if mode == "fixed":
        return f"{currency} {amount:,.0f} flat"
    if mode == "threshold" and threshold is not None:
        return f"{frac*100:.0f}% up to {threshold:,.0f}"
    return f"{frac*100:.0f}%"


def ocan_max_kwh(yearly_load_kwh: float, factor: float) -> float:
    """OCAN rule: the largest subsidised battery = yearly load / 365 x factor."""
    return yearly_load_kwh / 365 * factor


def battery_threshold_kwh(subsidies: dict, yearly_load_kwh: float) -> float:
    """The battery size up to which the subsidy applies: the OCAN rule (rounded) or the typed threshold."""
    b = subsidies["battery"]
    if b.get("threshold_mode") == "ocan":
        return round(ocan_max_kwh(yearly_load_kwh, b["ocan_factor"]))
    return b["threshold_kwh"]


def battery_net(size_kwh: float, capex: dict, subsidies: dict, threshold_kwh: float) -> float:
    """Net battery price of the first purchase."""
    b = subsidies["battery"]
    gross = capex_block.battery_gross(size_kwh, capex)
    cost_thr = capex_block.battery_gross(threshold_kwh, capex) if b["mode"] == "threshold" else None
    return apply_subsidy(gross, b["mode"], b["frac"], b["amount"],
                         size=size_kwh, threshold=threshold_kwh, cost_at_threshold=cost_thr)


def battery_label(subsidies: dict, threshold_kwh: float, currency: str) -> str:
    b = subsidies["battery"]
    return label(b["mode"], b["frac"], b["amount"], currency, threshold=threshold_kwh)


def pv_net(gross: float, modules: int, module_wp: float, capex: dict, subsidies: dict) -> float:
    """Net Voltiris PV price after the PV subsidy."""
    p = subsidies["pv"]
    thr = p.get("threshold_modules")
    thr = modules if thr is None else thr
    cost_thr = thr * module_wp * capex["pv_per_wp"] if p["mode"] == "threshold" else None
    return apply_subsidy(gross, p["mode"], p["frac"], p["amount"], size=modules, threshold=thr,
                         cost_at_threshold=cost_thr)


def pv_label(subsidies: dict, modules: int, currency: str) -> str:
    p = subsidies["pv"]
    thr = p.get("threshold_modules")
    return label(p["mode"], p["frac"], p["amount"], currency, threshold=modules if thr is None else thr)
