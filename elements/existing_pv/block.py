"""Existing PV: the PV already on site, its measured output (kW per step) from its own input file. It must run, like
Voltiris, and is not sized. The system adds it to the network together with Voltiris, as one PV generator behind the
site's meter (system/dispatch.py), as in the reference model. No parameter files: its cost is sunk."""
from __future__ import annotations

import pandas as pd

ID = "existing_pv"
CARRIERS = {"in": [], "out": ["electricity"]}
COLUMNS = [dict(role="existing_pv_kw", column="Current PV feed-in (kW)", about="output of the PV already on site",
                unit="kW", kind="power", needed="always")]
OWNS: dict = {}


class ExistingPV:
    def __init__(self, output_kw: pd.Series):
        self.pv = output_kw.fillna(0.0)
