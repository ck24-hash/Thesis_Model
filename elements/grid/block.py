"""Grid: the market (country, region, utility, tariff year), its tariff (tariffs.py), the import and export
connection, the capacity charges in the objective, and the A/B regime and its DUP lock. From
elements/battery_reference: parameters.load_tariff, engine/setup.py and the grid part of engine/dispatch.py.

The export value is given by the system (system/dispatch.py): the feed-in of the tariff, or the value the Voltiris
business model gives it under EaaS."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pypsa

from common import parameters as P
from common.network import BUS
from elements.grid.tariffs import Tariff

ID = "grid"
CARRIERS = {"in": ["electricity"], "out": ["electricity"]}
COLUMNS = [dict(role="day_ahead_eur_kwh", column="Day ahead kWh", about="day-ahead market price", unit="EUR/kWh",
                kind="price", needed="for day-ahead tariffs (NL, FR)")]
OWNS = {"tariff": None}
PARAMS_DIR = Path(__file__).resolve().parent / "params"
IMPORT, EXPORT = "grid_import", "grid_export"   # the battery model's names, kept so the LP is the same


def markets() -> list[dict]:
    out = []
    for path in sorted((PARAMS_DIR / "tariffs").glob("*/*/*.json")):
        if path.name.startswith("_"):
            continue
        utility, _, year = path.stem.rpartition("_")
        out.append({"country": path.parts[-3], "region": path.parts[-2], "utility": utility, "year": int(year)})
    return out


def tariff_files(market: dict) -> list[Path]:
    c, r, u, y = market["country"], market["region"], market["utility"], market["year"]
    base = PARAMS_DIR / "tariffs" / c
    return [base / "_country.json", base / r / "_canton.json", base / r / "_region.json", base / r / f"{u}_{y}.json"]


def load_params(market: dict, overrides: dict | None = None, fx: dict | None = None) -> dict:
    """{"tariff": the country, region and utility files merged}, money in the market's currency."""
    *general, utility = tariff_files(market)
    tariff = {}
    for path in general:
        tariff = P.deep_merge(tariff, P.read_optional(path))
    tariff = P.deep_merge(tariff, P.required(utility, "tariff"))
    tariff.update(country=market["country"], region=market["region"])
    if "currency" not in tariff:
        raise KeyError(f"{general[0].as_posix()} has no currency.")
    currency = tariff["currency"]
    fx = fx or P.fx_rates()
    params = P.finish({"tariff": tariff}, overrides, currency, fx)
    params["tariff"].setdefault("eur_to_local", P.eur_to_local(currency, fx))
    return params


class Grid:
    def __init__(self, params: dict, index: pd.DatetimeIndex, dt: float, day_ahead_eur: pd.Series | None = None,
                 import_max_kw: float | None = None, export_max_kw: float | None = None):
        self.params = params
        self.tariff = Tariff(params["tariff"])
        self.currency = self.tariff.currency
        self.index, self.dt = index, dt
        da = day_ahead_eur * params["tariff"].get("eur_to_local", 1.0) if day_ahead_eur is not None else None
        da = da if self.uses_day_ahead else None
        if self.uses_day_ahead and da is None:
            raise ValueError("This tariff prices on the day-ahead price, but the input has no day-ahead column "
                             "('Day ahead kWh', or the name given under 'columns' in the case file).")
        if da is not None and da.isna().any():
            raise ValueError(f"The day-ahead price is missing at {int(da.isna().sum())} steps; this tariff needs it "
                             f"at every step.")
        self.da = da
        self.import_max_kw = import_max_kw
        self.export_max_kw = export_max_kw
        self.battery_export = self.tariff.p.get("battery_export", "any")
        if self.battery_export not in ("any", "pv_only"):
            raise ValueError(f"battery_export must be 'any' or 'pv_only', not {self.battery_export!r}")
        self.hp_mask = self.tariff.hp_mask(index)
        self.winter_mask = self.tariff.winter_mask(index)
        self._prices: dict[str, pd.Series] = {}

    @property
    def uses_day_ahead(self) -> bool:
        return (any(c["by"] == "day_ahead" for _, c in self.tariff.components)
                or self.tariff.export["basis"] == "day_ahead")

    def import_price(self, regime: str) -> pd.Series:
        if regime not in self._prices:
            self._prices[regime] = self.tariff.import_price(self.index, regime, self.da)
        return self._prices[regime]

    def export_price(self):
        """The feed-in per kWh: a number (fixed) or a series (day-ahead)."""
        return self.tariff.export_price(self.index, self.da)

    def limits_kw(self, load_kw: pd.Series, pv_kw: pd.Series) -> tuple[float, float]:
        """Import and export limits; missing = automatic: 2 x the highest load, 1.1 x the highest PV."""
        p_imp = self.import_max_kw if self.import_max_kw is not None else float(load_kw.max()) * 2.0
        p_exp = self.export_max_kw if self.export_max_kw is not None else float(pv_kw.max()) * 1.1
        return p_imp, p_exp

    def choose_regime(self, grid_draw_kw: pd.Series, auto: bool = True,
                      manual: str | None = None) -> tuple[str, float | None]:
        """The regime from the DUP of a grid draw (the rule's regime), or the one the case gives."""
        if not auto or not self.tariff.rule:
            return manual or self.tariff.regime_names[0], None
        dup = self.tariff.dup(grid_draw_kw, self.hp_mask, self.dt)
        return self.tariff.regime_of(dup), dup

    # -- network -------------------------------------------------------------------------------------------------------
    def add_to(self, n: pypsa.Network, regime: str, import_max_kw: float, export_max_kw: float,
               export_static: float, export_value: pd.Series | None) -> None:
        """Import at the regime's price and export at the export value (a series when it varies, else the static
        number)."""
        n.add("Generator", IMPORT, bus=BUS, p_nom=import_max_kw, p_min_pu=0, marginal_cost=0)
        n.generators_t.marginal_cost[IMPORT] = self.import_price(regime)
        n.add("Generator", EXPORT, bus=BUS, p_nom=export_max_kw, p_min_pu=-1, p_max_pu=0, marginal_cost=export_static)
        if export_value is not None:
            n.generators_t.marginal_cost[EXPORT] = export_value

    def add_constraints(self, n: pypsa.Network, snapshots, regime: str, dup_lock: str | None) -> None:
        """The capacity charges in the objective (monthly peak with or without the annual ratchet, yearly peak, TURPE
        staircase), then the DUP lock: the year's DUP held at or below (A) or above (B) the threshold."""
        tariff, dt = self.tariff, self.dt
        m = n.model
        imp = m.variables["Generator-p"].sel(name=IMPORT)
        main = tariff.main_monthly_charge
        main_last = None
        for name, c in tariff.charges:
            if c["type"] == "monthly_peak":
                mask = tariff.window_mask(c["window"], pd.DatetimeIndex(snapshots))
                window_sns = [ts for ts, on in zip(snapshots, mask.values) if on]
                if not window_sns:
                    continue
                rate = tariff.charge_rate(c, regime)
                ratchet = c.get("ratchet") == "annual"
                prev = None
                for month in range(1, 13):
                    month_sns = [ts for ts in window_sns if ts.month == month]
                    if not month_sns and (prev is None or not ratchet):
                        continue
                    p_peak = m.add_variables(lower=0, name=f"{name}_peak_m{month:02d}")
                    if month_sns:
                        m.add_constraints(p_peak - imp.sel(snapshot=month_sns) >= 0, name=f"{name}_m{month:02d}")
                    if ratchet and prev is not None:
                        m.add_constraints(p_peak - prev >= 0, name=f"{name}_ratchet_m{month:02d}")
                    m.objective = m.objective + rate * p_peak
                    prev = p_peak
                if c is main:
                    main_last = prev
            elif c["type"] == "yearly_peak":
                mask = tariff.window_mask(c["window"], pd.DatetimeIndex(snapshots))
                sns = [ts for ts, on in zip(snapshots, mask.values) if on]
                if not sns:
                    continue
                p_peak = m.add_variables(lower=0, name=f"{name}_peak_year")
                m.add_constraints(p_peak - imp.sel(snapshot=sns) >= 0, name=f"{name}_year")
                m.objective = m.objective + tariff.charge_rate(c, regime) * p_peak
            elif c["type"] == "staircase":
                slots = tariff.slots(pd.DatetimeIndex(snapshots))
                rates = tariff.staircase_rates(c, regime)
                prev = None
                for i, (slot, b) in enumerate(rates):
                    sns = list(slots.index[(slots == slot).values])
                    p_s = m.add_variables(lower=0, name=f"{name}_{slot}")
                    if sns:
                        m.add_constraints(p_s - imp.sel(snapshot=sns) >= 0, name=f"{name}_{slot}_bound")
                    if prev is not None:
                        m.add_constraints(p_s - prev >= 0, name=f"{name}_{slot}_stair")
                    increment = b - rates[i + 1][1] if i < len(rates) - 1 else b
                    m.objective = m.objective + increment * p_s
                    prev = p_s
            else:
                raise ValueError(f"unknown capacity charge type {c['type']!r}")
        # DUP = yearly import / December's billed peak kept at or below (A) or above (B) the threshold. Under lock A
        # the LP may bill a peak above the metered one; in practice the controller just lets one HP interval reach it.
        if dup_lock is not None and main_last is not None and tariff.dup_threshold_h is not None:
            annual_imp = (imp * dt).sum()
            thr = tariff.dup_threshold_h
            if dup_lock == tariff.rule["at_or_below"]:
                m.add_constraints(thr * main_last - annual_imp >= 0, name=f"dup_lock_{dup_lock}")
            else:
                m.add_constraints(annual_imp - thr * main_last >= 0, name=f"dup_lock_{dup_lock}")
