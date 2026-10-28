"""Electricity tariffs: the import price per 15 minutes, the capacity charges, the export price, and the regime a site
falls under. Built from a tariff dict as parameters.load_tariff() returns it (country, region and utility merged).

The import price is a sum of components (in their "order"), each priced by one time classification:
    flat            one price per kWh (federal levies, energy tax, accise, transport)
    period          peak (HP) or off-peak (HD) hours
    season_period   winter or summer x HP or HD
    slot            the 5 TURPE slots: pointe, HPH, HCH (winter), HPB, HCB (summer)
    day_ahead       the day-ahead price of the step (a dynamic contract)
A component's price may depend on the regime (per_kwh_by_regime) and may carry the region's network levy.

Capacity charges are a set of components on the import power:
    monthly_peak    each month's max import in a window (peak hours or all), optionally ratcheted over the year
    yearly_peak     the year's max import in a window, per kW and year
    staircase       TURPE: one subscribed power per slot, non-decreasing pointe <= HPH <= HCH <= HPB <= HCB, each
                    slot's rate charged on its increment

The calendar gives winter months, peak hours per weekday, and the pointe (months, weekdays, hour windows). Regimes
(SIG Optimisation A/B, TURPE LU/CU) select prices; a regime_rule picks one from the site's DUP.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SLOTS = ["pointe", "HPH", "HCH", "HPB", "HCB"]


def _peak_hours(cal: dict) -> dict:
    """Peak hours per weekday name -> (start, end) or None. Accepts the short form {weekday, weekend}."""
    ph = cal.get("peak_hours") or {}
    if "weekday" in ph or "weekend" in ph:
        wd, we = ph.get("weekday"), ph.get("weekend")
        out = {d: (tuple(wd) if wd else None) if i < 5 else (tuple(we) if we else None) for i, d in enumerate(DAYS)}
    else:
        out = {d: (tuple(ph[d]) if ph.get(d) else None) for d in DAYS}
    for d, hours in out.items():
        if hours and not (0 <= hours[0] < hours[1] <= 24):
            raise ValueError(f"peak_hours {d}: {list(hours)} must be one window [start, end) with start < end "
                             f"within 0-24 (a window past midnight is not supported)")
    return out


class Tariff:
    def __init__(self, p: dict):
        self.p = p
        self.currency = p.get("currency", "EUR")
        self.eur_to_local = p.get("eur_to_local", 1.0)
        self.pricing = p.get("pricing", "bands")
        cal = p.get("calendar") or {}
        self.winter_months = set(cal.get("winter_months", []))
        self.peak = _peak_hours(cal)
        self.pointe = cal.get("pointe")
        regimes = p.get("regimes") or ["default"]
        self.regime_names = list(regimes)
        self.rule = p.get("regime_rule")
        self.network_levy = p.get("network_levy_pct", 0.0)
        self.components = sorted(p["import_price"].items(), key=lambda kv: kv[1].get("order", 0))
        self.charges = list((p.get("capacity_charges") or {}).items())
        self.export = p["export"]
        for name, c in self.charges:
            if c["type"] == "staircase":
                for regime in self.regime_names:
                    b = [self._rate(c, "per_kw_year", regime)[s] for s in c.get("slots", SLOTS)]
                    if any(b[i] < b[i + 1] for i in range(len(b) - 1)):
                        raise ValueError(f"capacity charge {name}: staircase rates must not rise from slot to slot")

    # -- calendar -----------------------------------------------------------------------------------------------------
    def is_hp(self, ts: pd.Timestamp) -> bool:
        hours = self.peak[DAYS[ts.weekday()]]
        return bool(hours) and hours[0] <= ts.hour < hours[1]

    def hp_mask(self, index: pd.DatetimeIndex) -> pd.Series:
        """True in peak (HP) hours."""
        wd = index.weekday
        start = np.array([self.peak[d][0] if self.peak[d] else 0 for d in DAYS])[wd]
        end = np.array([self.peak[d][1] if self.peak[d] else 0 for d in DAYS])[wd]
        return pd.Series((index.hour >= start) & (index.hour < end), index=index)

    def winter_mask(self, index: pd.DatetimeIndex) -> pd.Series:
        return pd.Series(index.month.isin(sorted(self.winter_months)), index=index)

    def pointe_mask(self, index: pd.DatetimeIndex) -> pd.Series:
        if not self.pointe:
            return pd.Series(False, index=index)
        days = [DAYS.index(d) for d in self.pointe["days"]]
        hours = np.zeros(len(index), dtype=bool)
        for start, end in self.pointe["hours"]:
            hours |= (index.hour >= start) & (index.hour < end)
        return pd.Series(index.month.isin(self.pointe["months"]) & index.weekday.isin(days) & hours, index=index)

    def slots(self, index: pd.DatetimeIndex) -> pd.Series:
        """The TURPE slot of each step: pointe, HPH, HCH (winter), HPB, HCB (summer)."""
        hp, win, pt = self.hp_mask(index).values, self.winter_mask(index).values, self.pointe_mask(index).values
        out = np.where(win, np.where(hp, "HPH", "HCH"), np.where(hp, "HPB", "HCB")).astype(object)
        out[pt] = "pointe"
        return pd.Series(out, index=index)

    def window_mask(self, window: str, index: pd.DatetimeIndex) -> pd.Series:
        if window == "peak":
            return self.hp_mask(index)
        if window == "offpeak":
            return ~self.hp_mask(index)
        if window == "all":
            return pd.Series(True, index=index)
        raise ValueError(f"unknown window {window!r}")

    # -- regimes ------------------------------------------------------------------------------------------------------
    def regime_of(self, dup_h: float) -> str:
        """The regime a site with this DUP (hours) falls under; the first regime when the tariff has no rule."""
        if not self.rule:
            return self.regime_names[0]
        return self.rule["at_or_below"] if dup_h <= self.rule["threshold_h"] else self.rule["above"]

    def other_regime(self, regime: str) -> str | None:
        others = [r for r in self.regime_names if r != regime]
        return others[0] if others else None

    @property
    def dup_threshold_h(self) -> float | None:
        return self.rule["threshold_h"] if self.rule else None

    @staticmethod
    def dup(import_kw: pd.Series, hp_mask: pd.Series, dt: float) -> float:
        """DUP in hours: yearly import kWh / yearly HP peak kW."""
        peak = import_kw[hp_mask].max()
        return (import_kw * dt).sum() / peak if peak > 0 else 0.0

    @staticmethod
    def _rate(c: dict, key: str, regime: str):
        if f"{key}_by_regime" in c:
            return c[f"{key}_by_regime"][regime]
        return c[key]

    # -- import price -------------------------------------------------------------------------------------------------
    def _component(self, c: dict, index: pd.DatetimeIndex, regime: str, da) -> np.ndarray:
        by = c["by"]
        if by == "day_ahead":
            if da is None:
                raise ValueError("this tariff prices on the day-ahead price, but the input has no day-ahead series")
            values = np.asarray(da, dtype=float) * c.get("factor", 1.0)
        else:
            v = self._rate(c, "per_kwh", regime)
            if by == "flat":
                values = np.full(len(index), float(v))
            elif by == "period":
                values = np.where(self.hp_mask(index).values, v["HP"], v["HD"])
            elif by == "season_period":
                hp, win = self.hp_mask(index).values, self.winter_mask(index).values
                values = np.where(win, np.where(hp, v["winter"]["HP"], v["winter"]["HD"]),
                                  np.where(hp, v["summer"]["HP"], v["summer"]["HD"]))
            elif by == "slot":
                values = self.slots(index).map(v).values.astype(float)
            else:
                raise ValueError(f"unknown price classification {by!r}")
        if c.get("apply_network_levy"):
            values = values * (1 + self.network_levy)
        return values

    def import_price(self, index: pd.DatetimeIndex, regime: str, da=None) -> pd.Series:
        """Import price per kWh at each step, excl. VAT and the capacity charges."""
        total = None
        for _, c in self.components:
            values = self._component(c, index, regime, da)
            total = values if total is None else total + values
        return pd.Series(total, index=index)

    def import_price_parts(self, index: pd.DatetimeIndex, regime: str, da=None) -> dict:
        return {name: pd.Series(self._component(c, index, regime, da), index=index) for name, c in self.components}

    # -- export price -------------------------------------------------------------------------------------------------
    def export_price(self, index: pd.DatetimeIndex, da=None):
        """The price of 1 kWh exported: a number (fixed feed-in) or a series (day-ahead)."""
        if self.export["basis"] == "fixed":
            return self.export["per_kwh"]
        if self.export["basis"] == "day_ahead":
            if da is None:
                raise ValueError("this tariff pays exports at the day-ahead price, but the input has no day-ahead series")
            return pd.Series(np.asarray(da, dtype=float), index=index)
        raise ValueError(f"unknown export basis {self.export['basis']!r}")

    # -- capacity charges ---------------------------------------------------------------------------------------------
    def charge_rate(self, c: dict, regime: str) -> float:
        """The rate of a monthly_peak (per kW and month) or yearly_peak (per kW and year) charge, levy included."""
        key = "per_kw_month" if c["type"] == "monthly_peak" else "per_kw_year"
        rate = self._rate(c, key, regime)
        return rate * (1 + self.network_levy) if c.get("apply_network_levy") else rate

    def staircase_rates(self, c: dict, regime: str) -> list[tuple[str, float]]:
        b = self._rate(c, "per_kw_year", regime)
        levy = (1 + self.network_levy) if c.get("apply_network_levy") else 1.0
        return [(s, b[s] * levy) for s in c.get("slots", SLOTS)]

    def billed_peaks(self, c: dict, import_kw: pd.Series) -> pd.Series:
        """A monthly_peak charge: the billed peak of each month 1..12 (running max since 1 January if ratcheted)."""
        w = import_kw[self.window_mask(c["window"], import_kw.index)]
        monthly = w.groupby(w.index.month).max().reindex(range(1, 13), fill_value=0.0)
        return monthly.cummax() if c.get("ratchet") == "annual" else monthly

    def subscribed_powers(self, c: dict, import_kw: pd.Series) -> dict:
        """A staircase charge: the smallest non-decreasing subscribed power per slot that covers the imports."""
        slots = self.slots(import_kw.index)
        out, prev = {}, 0.0
        for s in c.get("slots", SLOTS):
            mask = (slots == s).values
            p = float(import_kw[mask].max()) if mask.any() else 0.0
            prev = max(prev, p)
            out[s] = prev
        return out

    def charge_cost(self, c: dict, import_kw: pd.Series, regime: str) -> float:
        """The year's cost of one capacity charge."""
        if c["type"] == "monthly_peak":
            return sum(self.demand_charge_month(c, p, regime) for p in self.billed_peaks(c, import_kw))
        if c["type"] == "yearly_peak":
            w = import_kw[self.window_mask(c["window"], import_kw.index)]
            return (float(w.max()) if len(w) else 0.0) * self.charge_rate(c, regime)
        if c["type"] == "staircase":
            powers = self.subscribed_powers(c, import_kw)
            cost, prev = 0.0, 0.0
            for s, b in self.staircase_rates(c, regime):
                cost += b * (powers[s] - prev)
                prev = powers[s]
            return cost
        raise ValueError(f"unknown capacity charge type {c['type']!r}")

    def demand_charge_month(self, c: dict, peak_kw: float, regime: str) -> float:
        """One month's monthly_peak charge for a billed peak."""
        rate = self._rate(c, "per_kw_month", regime)
        return peak_kw * rate * (1 + self.network_levy) if c.get("apply_network_levy") else peak_kw * rate

    def yearly_capacity_charge(self, import_kw: pd.Series, regime: str) -> float:
        """All capacity charges of the year."""
        return sum(self.charge_cost(c, import_kw, regime) for _, c in self.charges)

    def capacity_charges_by_name(self, import_kw: pd.Series, regime: str) -> dict:
        return {name: self.charge_cost(c, import_kw, regime) for name, c in self.charges}

    def monthly_capacity_charge(self, import_kw: pd.Series, regime: str) -> np.ndarray:
        """The capacity charges per month 1..12: monthly charges as billed, yearly ones spread as 1/12."""
        out = np.zeros(12)
        for _, c in self.charges:
            if c["type"] == "monthly_peak":
                out += np.array([self.demand_charge_month(c, p, regime) for p in self.billed_peaks(c, import_kw)])
            else:
                out += self.charge_cost(c, import_kw, regime) / 12
        return out

    @property
    def main_monthly_charge(self) -> dict | None:
        """The first monthly_peak charge (SIG's demand charge), used for the DUP lock and the monthly table."""
        return next((c for _, c in self.charges if c["type"] == "monthly_peak"), None)

    # -- the bill by component ----------------------------------------------------------------------------------------
    def import_cost_breakdown(self, import_kw: pd.Series, regime: str, dt: float, da=None) -> dict:
        """The year's import bill by component: each import price component, each capacity charge."""
        index = import_kw.index
        out = {}
        imp_cost = 0.0
        for name, series in self.import_price_parts(index, regime, da).items():
            cost = (import_kw * series * dt).sum()
            out[f"import_{name}"] = cost
            imp_cost += cost
        charges = self.capacity_charges_by_name(import_kw, regime)
        for name, cost in charges.items():
            out[f"capacity_{name}"] = cost
        main = self.main_monthly_charge
        peak = float(import_kw[self.window_mask(main["window"], index)].max()) if main else float(import_kw.max())
        out.update(imp_cost=imp_cost, demand=sum(charges.values()), kwh=import_kw.sum() * dt, peak_kw=peak)
        return out
