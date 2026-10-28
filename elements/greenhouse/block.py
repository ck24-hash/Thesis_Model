"""Greenhouse demand: the site's electricity load, kW per step, from the input workbook. Heat and CO2 demand are not
built yet (PLAN.md section 6, step 2). No parameter files yet."""
from __future__ import annotations

import pandas as pd
import pypsa

from common.network import BUS

ID = "greenhouse"
CARRIERS = {"in": ["electricity"], "out": []}
COLUMNS = [dict(role="load_kw", column="Loadcurve (kW)", about="the site's consumption", unit="kW", kind="power",
                needed="always")]
OWNS: dict = {}   # parameter groups this block owns (none yet)


class Greenhouse:
    def __init__(self, load_kw: pd.Series, dt: float):
        self.load = load_kw
        self.dt = dt

    @property
    def yearly_load_kwh(self) -> float:
        return (self.load * self.dt).sum()

    def add_to(self, n: pypsa.Network) -> None:
        n.add("Load", "load", bus=BUS, p_set=self.load)
