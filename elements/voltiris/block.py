"""Voltiris: the modules' electricity, kW per step = yield of one module (W) / 1000 x module count. It must run (no
curtailment). The block also holds what the modules cost (price per Wp, subsidy, life) and the business model: direct
sales, or EaaS, which changes the value of exports and the grid bounds (applied by the system, system/dispatch.py)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pypsa

from common import parameters as P
from common.money import apply_subsidy, subsidy_label
from common.network import add_must_run
from elements.voltiris.business_model import BusinessModel

ID = "voltiris"
CARRIERS = {"in": [], "out": ["electricity"]}
COLUMNS = [dict(role="pv_w_per_module", column="Production voltiron (W)", about="yield of one Voltiris module",
                unit="W per module", kind="power", needed="always")]
OWNS = {"tech": ["module_wp"], "capex": ["pv_per_wp"], "finance": ["pv_life_yr"], "subsidies": ["pv"],
        "business_model": None}
PARAMS_DIR = Path(__file__).resolve().parent / "params"
GENERATOR = "pv"   # the battery model's name, kept so the LP is the same


def business_models() -> list[str]:
    return sorted(p.stem for p in (PARAMS_DIR / "business_models").glob("*.json"))


def load_params(market: dict, currency: str, business_model: str = "direct_sales", overrides: dict | None = None,
                fx: dict | None = None) -> dict:
    c, r = market["country"], market["region"]
    params = {
        "subsidies": P.by_place(PARAMS_DIR / "subsidies", c, r),
        "capex": P.shared(PARAMS_DIR / "capex", c),
        "finance": P.shared(PARAMS_DIR / "finance", c),
        "tech": P.shared(PARAMS_DIR / "tech", c),
        "business_model": P.required(PARAMS_DIR / "business_models" / f"{business_model}.json", "business model"),
    }
    return P.finish(params, overrides, currency, fx)


class Voltiris:
    def __init__(self, params: dict, yield_w_per_module: pd.Series, modules: int):
        self.params = params
        self.modules = modules
        self.module_wp = params["tech"]["module_wp"]
        self.life_yr = params["finance"]["pv_life_yr"]
        self.pv = (yield_w_per_module / 1000) * modules

    def add_to(self, n: pypsa.Network) -> None:
        add_must_run(n, GENERATOR, self.pv)

    def business_model(self, pv_total_kw: pd.Series, feed_in, dt: float) -> BusinessModel:
        """feed_in: the grid's export price (a number or a series)."""
        return BusinessModel(self.params["business_model"], self.modules, self.pv, pv_total_kw, feed_in, dt)

    # -- money ---------------------------------------------------------------------------------------------------------
    def gross_capex(self) -> float:
        return self.modules * self.module_wp * self.params["capex"]["pv_per_wp"]

    def net_capex(self, gross: float) -> float:
        """The modules' price after the PV subsidy."""
        p = self.params["subsidies"]["pv"]
        thr = p.get("threshold_modules")
        thr = self.modules if thr is None else thr
        cost_thr = thr * self.module_wp * self.params["capex"]["pv_per_wp"] if p["mode"] == "threshold" else None
        return apply_subsidy(gross, p["mode"], p["frac"], p["amount"], size=self.modules, threshold=thr,
                             cost_at_threshold=cost_thr)

    def subsidy_label(self, currency: str) -> str:
        p = self.params["subsidies"]["pv"]
        thr = p.get("threshold_modules")
        return subsidy_label(p["mode"], p["frac"], p["amount"], currency,
                             threshold=self.modules if thr is None else thr)


def without_modules(pv_total_kw: pd.Series, feed_in, dt: float) -> BusinessModel:
    """The business model of a system without Voltiris: direct sales, every export paid at the feed-in."""
    return BusinessModel({"type": "direct_sales"}, 0, pv_total_kw * 0.0, pv_total_kw, feed_in, dt)
