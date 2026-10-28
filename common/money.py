"""Money rules shared by the blocks: subsidies, payback and lifetime profit (from elements/battery_reference
blocks/subsidies.py and blocks/finance.py)."""
from __future__ import annotations


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


def subsidy_label(mode: str, frac: float, amount: float, currency: str = "CHF", threshold: float | None = None) -> str:
    if mode == "fixed":
        return f"{currency} {amount:,.0f} flat"
    if mode == "threshold" and threshold is not None:
        return f"{frac*100:.0f}% up to {threshold:,.0f}"
    return f"{frac*100:.0f}%"


def payback_years(net_capex: float, saving_per_year: float) -> float:
    return net_capex / saving_per_year if saving_per_year > 0 else float("inf")


def lifetime_profit(saving_per_year: float, life_yr: float, net_capex: float) -> float:
    return saving_per_year * life_yr - net_capex
