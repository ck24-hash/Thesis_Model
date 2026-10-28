"""Voltiris: the modules' electricity, kW per step = yield of one module (W, from its own input file) / 1000 x module
count. It must run (no curtailment). The system adds it to the network together with the existing PV, as one PV
generator behind the site's meter (system/dispatch.py), as in the reference model. Its price, subsidy, life and
business model are general items (general/commercial, general/subsidies)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from common import parameters as P

ID = "voltiris"
CARRIERS = {"in": [], "out": ["electricity"]}
COLUMNS = [dict(role="pv_w_per_module", column="Production voltiron (W)", about="yield of one Voltiris module",
                unit="W per module", kind="power", needed="always")]
OWNS = {"tech": ["module_wp", "module_wp_note"]}
PARAMS_DIR = Path(__file__).resolve().parent / "params"


def load_params(market: dict, currency: str, overrides: dict | None = None, fx: dict | None = None) -> dict:
    return P.finish({"tech": P.shared(PARAMS_DIR / "tech", market["country"])}, overrides, currency, fx)


class Voltiris:
    def __init__(self, params: dict, yield_w_per_module: pd.Series, modules: int):
        self.params = params
        self.modules = modules
        self.module_wp = params["tech"]["module_wp"]
        self.pv = (yield_w_per_module / 1000) * modules
