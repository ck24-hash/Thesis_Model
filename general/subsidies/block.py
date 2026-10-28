"""Subsidies on the Voltiris modules and on the battery, per country and region: a percent, a fixed amount, or a
percent up to a threshold size (CH's OCAN rule sets the battery threshold from the site's yearly load). From
elements/battery_reference blocks/subsidies.py."""
from __future__ import annotations

from pathlib import Path

from common import parameters as P
from common.money import apply_subsidy, subsidy_label

ID = "subsidies"
OWNS = {"subsidies": None}
PARAMS_DIR = Path(__file__).resolve().parent / "params"


def load_params(market: dict, currency: str, overrides: dict | None = None, fx: dict | None = None) -> dict:
    params = {"subsidies": P.by_place(PARAMS_DIR / "subsidies", market["country"], market["region"])}
    return P.finish(params, overrides, currency, fx)


class Subsidies:
    def __init__(self, params: dict, yearly_load_kwh: float):
        """yearly_load_kwh: the site's load, for a threshold that depends on it (OCAN)."""
        self.params = params
        self.battery = params["subsidies"]["battery"]
        self.pv = params["subsidies"]["pv"]
        b = self.battery
        # OCAN rule: the largest subsidised battery = yearly load / 365 x factor (rounded), or the typed threshold
        self.battery_threshold_kwh = (round(yearly_load_kwh / 365 * b["ocan_factor"])
                                      if b.get("threshold_mode") == "ocan" else b["threshold_kwh"])

    @property
    def cap_sweep_at_subsidy(self) -> bool:
        """The battery sweep stops at the subsidised maximum only for a threshold subsidy (CH's OCAN rule)."""
        return self.battery["mode"] == "threshold" and self.battery.get("frac", 0) > 0

    def battery_net(self, size_kwh: float, gross_of) -> float:
        """Net price of the battery's first purchase; gross_of(size) is its gross price (general/commercial)."""
        b = self.battery
        gross = gross_of(size_kwh)
        cost_thr = gross_of(self.battery_threshold_kwh) if b["mode"] == "threshold" else None
        return apply_subsidy(gross, b["mode"], b["frac"], b["amount"],
                             size=size_kwh, threshold=self.battery_threshold_kwh, cost_at_threshold=cost_thr)

    def pv_net(self, gross: float, modules: int, module_wp: float, pv_per_wp: float) -> float:
        """Net price of the Voltiris modules."""
        p = self.pv
        thr = p.get("threshold_modules")
        thr = modules if thr is None else thr
        cost_thr = thr * module_wp * pv_per_wp if p["mode"] == "threshold" else None
        return apply_subsidy(gross, p["mode"], p["frac"], p["amount"], size=modules, threshold=thr,
                             cost_at_threshold=cost_thr)

    def battery_label(self, currency: str) -> str:
        b = self.battery
        return subsidy_label(b["mode"], b["frac"], b["amount"], currency, threshold=self.battery_threshold_kwh)

    def pv_label(self, modules: int, currency: str) -> str:
        p = self.pv
        thr = p.get("threshold_modules")
        return subsidy_label(p["mode"], p["frac"], p["amount"], currency, threshold=modules if thr is None else thr)
