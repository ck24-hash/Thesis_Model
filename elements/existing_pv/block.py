"""Existing PV: the PV already on site, its measured output (kW per step) from the input workbook. It must run, like
Voltiris, and is not sized. No parameter files: its cost is sunk."""
from __future__ import annotations

import pandas as pd
import pypsa

from common.network import add_must_run

ID = "existing_pv"
CARRIERS = {"in": [], "out": ["electricity"]}
COLUMNS = [dict(role="existing_pv_kw", column="Current PV feed-in (kW)", about="existing PV already on site",
                unit="kW", kind="power", needed="with existing PV")]
OWNS: dict = {}
GENERATOR = "existing_pv"


class ExistingPV:
    def __init__(self, output_kw: pd.Series):
        self.pv = output_kw.fillna(0.0)

    def add_to(self, n: pypsa.Network) -> None:
        add_must_run(n, GENERATOR, self.pv)
