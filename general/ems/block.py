"""Energy management system (EMS): a fixed yearly cost, fees on the ancillary revenue and on the bill saving, and
hardware bought once with the battery (ems.py, from elements/battery_reference blocks/ems.py)."""
from __future__ import annotations

from pathlib import Path

from common import parameters as P
from general.ems.ems import Ems  # noqa: F401  (the class the system builds)

ID = "ems"
OWNS = {"ems": None}
PARAMS_DIR = Path(__file__).resolve().parent / "params"


def load_params(market: dict, currency: str, overrides: dict | None = None, fx: dict | None = None) -> dict:
    return P.finish({"ems": P.shared(PARAMS_DIR / "ems", market["country"])}, overrides, currency, fx)
