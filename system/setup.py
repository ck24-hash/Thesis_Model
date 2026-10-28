"""A run's system: the chosen blocks built from a case, on one time index, with what follows from having them together
(the PV that must run, the business model applied to exports). The engine functions (system/dispatch.py,
system/flows.py) take a System and the regime explicitly, so nothing is global.

Case file in the system format (keys as in the battery model's case file, plus "blocks"):
    input_file, year, columns, market, overrides, tag, output_dir
    blocks   {"greenhouse": {},
              "voltiris": {"modules": 500, "business_model": "direct_sales"},
              "existing_pv": {},
              "grid": {"import_max_kw": 750, "export_max_kw": 750, "regime": {"auto": true}},
              "battery": {"sizing": {"objective": "profit", "sweep_kwh": [100, 200]}}}
A block that is not listed is not in the system. overrides keep the battery model's layout ({"tech": {...},
"tariff": {...}}); each value goes to the block that owns it (each block's OWNS). A battery model case file (no
"blocks") is read as the same system: see from_battery_case().
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from common import parameters as P
from common.timeseries import MODEL_STEP_MIN
from elements.battery import block as battery
from elements.existing_pv import block as existing_pv
from elements.greenhouse import block as greenhouse
from elements.grid import block as grid
from elements.voltiris import block as voltiris

# the blocks that can be built, in the order they are added to the network (the battery model's order)
BLOCKS = {m.ID: m for m in (voltiris, existing_pv, greenhouse, grid, battery)}
REQUIRED = ("greenhouse", "grid")
TIME_COLUMNS = {"month": "Month", "day": "Day", "hour": "Hour", "minute": "Minute"}
DT = MODEL_STEP_MIN / 60


def default_columns() -> dict:
    return {**TIME_COLUMNS, **{c["role"]: c["column"] for m in BLOCKS.values() for c in m.COLUMNS}}


def read_frame(df: pd.DataFrame, year: int, columns: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """The workbook's rows on a time index built from Month, Day, Hour, Minute and the year (engine/inputs.py)."""
    c = {**default_columns(), **(columns or {})}
    df = df.dropna(subset=[c["month"], c["day"], c["hour"], c["minute"]]).reset_index(drop=True)
    df["timestamp"] = pd.to_datetime(dict(year=year, month=df[c["month"]], day=df[c["day"]],
                                          hour=df[c["hour"]], minute=df[c["minute"]]))
    return df.set_index("timestamp"), c


class System:
    def __init__(self, frame: pd.DataFrame, columns: dict, market: dict, blocks: dict, overrides: dict | None = None,
                 dt: float = DT, one_meter: bool = True):
        not_built = sorted(set(blocks) - set(BLOCKS))
        if not_built:
            raise ValueError(f"Not built yet: {', '.join(not_built)}. The blocks that run are {', '.join(BLOCKS)}.")
        missing = [b for b in REQUIRED if b not in blocks]
        if missing:
            raise ValueError(f"A system needs {', '.join(REQUIRED)}; missing: {', '.join(missing)}.")
        self.market, self.dt, self.index = market, dt, frame.index
        self.chosen = [b for b in BLOCKS if b in blocks]
        owned = P.split_overrides(overrides, {key: m.OWNS for key, m in BLOCKS.items()})
        fx = P.fx_rates()

        def column(role: str) -> pd.Series:
            if columns[role] not in frame.columns:
                raise KeyError(f"Column '{columns[role]}' ({role}) is missing. Available columns: {list(frame.columns)}")
            return frame[columns[role]]

        grid_params = grid.load_params(market, owned["grid"], fx)
        self.currency = grid_params["tariff"]["currency"]
        self.greenhouse = greenhouse.Greenhouse(column("load_kw"), dt)
        v = blocks.get("voltiris")
        self.voltiris = None if v is None else voltiris.Voltiris(
            voltiris.load_params(market, self.currency, v.get("business_model", "direct_sales"), owned["voltiris"], fx),
            column("pv_w_per_module"), int(v.get("modules", 0)))
        self.existing_pv = existing_pv.ExistingPV(column("existing_pv_kw")) if "existing_pv" in blocks else None
        g = blocks["grid"] or {}
        da_column = columns["day_ahead_eur_kwh"]
        self.grid = grid.Grid(grid_params, self.index, dt, frame[da_column] if da_column in frame.columns else None,
                              g.get("import_max_kw"), g.get("export_max_kw"))
        self.battery = None if "battery" not in blocks else battery.Battery(
            battery.load_params(market, self.currency, owned["battery"], fx), self.greenhouse.yearly_load_kwh)

        # what the blocks give together
        self.load = self.greenhouse.load
        self.modules = self.voltiris.modules if self.voltiris else 0
        self.volt_pv = self.voltiris.pv if self.voltiris else self.load * 0.0
        self.existing = self.existing_pv.pv if self.existing_pv else None
        self.pv_total = self.volt_pv + self.existing if self.existing is not None else self.volt_pv
        feed_in = self.grid.export_price()
        self.bm = (self.voltiris.business_model(self.pv_total, feed_in, dt) if self.voltiris
                   else voltiris.without_modules(self.pv_total, feed_in, dt))
        # the horizon of the payback and of battery replacements: the PV life (from the Voltiris parameters even
        # without Voltiris, as the battery model does with 0 modules)
        self.pv_life_yr = (self.voltiris.life_yr if self.voltiris else
                           voltiris.load_params(market, self.currency, overrides=owned["voltiris"], fx=fx)
                           ["finance"]["pv_life_yr"])
        self.one_meter = one_meter   # no import and export in the same step, exact where it could pay (dispatch)
        self.battery_export = self.grid.battery_export

    def import_price(self, regime: str) -> pd.Series:
        return self.grid.import_price(regime)

    @property
    def eta2(self) -> float:
        """The battery's round trip (1 without a battery)."""
        return self.battery.tech.eta2 if self.battery else 1.0


def parameters(market: dict, business_model: str = "direct_sales", overrides: dict | None = None) -> dict:
    """The grid's, Voltiris's and the battery's parameters for a market in one dict (the battery model's layout),
    money in the market's currency, overrides applied."""
    owned = P.split_overrides(overrides, {key: m.OWNS for key, m in BLOCKS.items()})
    fx = P.fx_rates()
    out = grid.load_params(market, owned["grid"], fx)
    currency = out["tariff"]["currency"]
    out = P.deep_merge(out, voltiris.load_params(market, currency, business_model, owned["voltiris"], fx))
    return P.deep_merge(out, battery.load_params(market, currency, owned["battery"], fx))


# -- case files ------------------------------------------------------------------------------------------------------
def from_battery_case(case: dict) -> dict:
    """A battery model case file as a system case: its blocks are case["system"]["blocks"] when the interface wrote
    them, else greenhouse + Voltiris (pv_modules, 0 included) + grid + battery, with existing PV when
    use_existing_pv is true."""
    chosen = (case.get("system") or {}).get("blocks")
    chosen = set(chosen) if chosen else ({"greenhouse", "voltiris", "grid", "battery"}
                                         | ({"existing_pv"} if case.get("use_existing_pv") else set()))
    blocks: dict = {b: {} for b in chosen}
    if "voltiris" in blocks:
        blocks["voltiris"] = {"modules": case.get("pv_modules", 0),
                              "business_model": case.get("business_model", "direct_sales")}
    if "grid" in blocks:
        blocks["grid"] = {**(case.get("grid") or {}), "regime": case.get("regime") or {}}
    if "battery" in blocks:
        blocks["battery"] = {"sizing": case.get("sizing")}
    out = {k: case[k] for k in ("input_file", "year", "columns", "market", "overrides", "tag", "output_dir")
           if k in case}
    out["blocks"] = blocks
    return out


def as_system_case(case: dict) -> dict:
    return case if "blocks" in case else from_battery_case(case)


def load_case(path: Path) -> dict:
    case = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("input_file", "market"):
        if key not in case:
            raise KeyError(f"The case file has no '{key}'.")
    return as_system_case(case)


def from_frame(df: pd.DataFrame, case: dict) -> System:
    """The system of a case (either format) from the workbook's first sheet."""
    case = as_system_case(case)
    m = case["market"]
    market = {**m, "region": m.get("region", m.get("canton"))}
    frame, columns = read_frame(df, case.get("year", m["year"]), case.get("columns"))
    return System(frame, columns, market, case["blocks"], case.get("overrides"))


def build(case: dict, case_dir: Path) -> System:
    """The system of a case, reading its workbook (input_file relative to case_dir or absolute)."""
    input_path = Path(case["input_file"])
    if not input_path.is_absolute():
        input_path = case_dir / input_path
    return from_frame(pd.read_excel(input_path), case)
