"""Greenhouse demand: the site's electricity load, heat demand and CO2 demand, per step, from the block's one input
file. The electricity load is always read. Heat and CO2 demand are read when a block supplies them (today the gas
boiler):

    heat   must be met: a Load on the heat bus; heat_unmet (a slack at a penalty) only keeps the year solvable when the
           heat blocks are too small, and a size that needs it is not chosen.
    CO2    co2_mode "required" (default): must be met the same way, so the boiler may run for CO2 alone and release
           its surplus heat (thesis.md A4); "by_product": the greenhouse takes the CO2 the heat blocks give while they
           run, up to its demand, and the rest is recorded as unmet.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pypsa

from common import parameters as P
from common.network import BUS

ID = "greenhouse"
CARRIERS = {"in": ["electricity", "heat", "co2"], "out": []}
COLUMNS = [
    dict(role="load_kw", column="Loadcurve (kW)", about="the site's electricity consumption", unit="kW", kind="power",
         needed="always"),
    dict(role="heat_kw", column="Heat demand (kW)", about="heat demand", unit="kW", kind="power",
         needed="with a heat block (gas boiler)"),
    dict(role="co2_kg_h", column="CO2 demand (kg/h)", about="CO2 demand for enrichment", unit="kg/h", kind="power",
         needed="with a CO2 source (gas boiler)"),
]
OWNS = {"demand": None}
PARAMS_DIR = Path(__file__).resolve().parent / "params"
CO2_MODES = ("required", "by_product")
HEAT_BUS, CO2_BUS = "heat", "co2"


def load_params(market: dict, currency: str, overrides: dict | None = None, fx: dict | None = None) -> dict:
    return P.finish({"demand": P.shared(PARAMS_DIR / "demand", market["country"])}, overrides, currency, fx)


class Greenhouse:
    def __init__(self, params: dict, load_kw: pd.Series, dt: float, heat_kw: pd.Series | None = None,
                 co2_kg_h: pd.Series | None = None, co2_mode: str = "required"):
        if co2_mode not in CO2_MODES:
            raise ValueError(f"co2_mode must be one of {CO2_MODES}, not {co2_mode!r}")
        self.params = params
        self.load = load_kw
        self.heat = heat_kw.fillna(0.0) if heat_kw is not None else None
        self.co2 = co2_kg_h.fillna(0.0) if co2_kg_h is not None else None
        self.co2_mode = co2_mode
        self.dt = dt

    @property
    def yearly_load_kwh(self) -> float:
        return (self.load * self.dt).sum()

    def add_to(self, n: pypsa.Network) -> None:
        n.add("Load", "load", bus=BUS, p_set=self.load)

    def add_heat_co2_to(self, n: pypsa.Network, slack: bool = True) -> None:
        """The heat demand and, when it must be met, the CO2 demand, each with its slack. slack=False: no slack, the
        demand must be met (the joint sizing, where the heat blocks' sizes are free)."""
        d = self.params["demand"]
        n.add("Load", "heat_demand", bus=HEAT_BUS, p_set=self.heat)
        if slack:
            n.add("Generator", "heat_unmet", bus=HEAT_BUS, p_nom=max(float(self.heat.max()), 1.0),
                  marginal_cost=d["unmet_heat_penalty_per_kwh"])
        if self.co2_mode == "required":
            n.add("Load", "co2_demand", bus=CO2_BUS, p_set=self.co2)
            if slack:
                n.add("Generator", "co2_unmet", bus=CO2_BUS, p_nom=max(float(self.co2.max()), 1.0),
                      marginal_cost=d["unmet_co2_penalty_per_kg"])
