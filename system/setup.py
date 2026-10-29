"""A run's system: the chosen blocks built from a case, each from its own input file, on one time index, with what
follows from having them together (the PV that must run, the business model applied to exports). The engine
functions (system/dispatch.py, system/flows.py) take a System and the regime explicitly, so nothing is global.

Case file in the system format:
    year, market, overrides, tag, output_dir
    blocks   {"greenhouse": {"input_file": "greenhouse_load.xlsx"},
              "voltiris": {"input_file": "voltiris_yield.xlsx", "modules": 500, "business_model": "direct_sales"},
              "existing_pv": {"input_file": "existing_pv.xlsx"},
              "grid": {"input_file": "grid_day_ahead.xlsx", "import_max_kw": 750, "export_max_kw": 750,
                       "regime": {"auto": true}},
              "battery": {"sizing": {"objective": "profit", "sweep_kwh": [100, 200]}}}
Each block with input columns has its own input_file (relative to the case file, or absolute) and may rename its
columns, time columns included, under "columns". Blocks may share a file. A block not listed is not in the system.
The grid's file is only needed where the tariff uses the day-ahead price (NL, FR). overrides keep the reference
model's layout ({"tech": {...}, "tariff": {...}}); each value goes to the block that owns it (each block's OWNS).

Input files: one row per step with Month, Day, Hour (and Minute; 0 when missing), read with the case's year. The
greenhouse load's time stamps are the run's; a file with a coarser step (hourly, 30 min) is brought to 15 min
(common/timeseries.py: kW, W and prices repeated, kWh per step divided), and every file must cover those time stamps.

General items (general/): what is not a physical block. "general": {"commercial": {"business_model": "eaas"}} picks
the business model (default direct sales); commercial (prices, lifetimes, ancillary rate), subsidies and EMS have no
other setting than their parameter files and the overrides.

A reference case file (one input_file for everything, no "blocks") is read as the same system: from_battery_case().
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from common import parameters as P
from common import timeseries
from elements.battery import block as battery
from elements.existing_pv import block as existing_pv
from elements.gas_supply import block as gas_supply
from elements.greenhouse import block as greenhouse
from elements.grid import block as grid
from elements.ng_boiler import block as ng_boiler
from elements.thermal_storage import block as thermal_storage
from elements.voltiris import block as voltiris
from general.commercial import block as commercial
from general.ems import block as ems
from general.subsidies import block as subsidies

# the blocks that can be built; greenhouse first: its load file sets the run's time stamps
BLOCKS = {m.ID: m for m in (greenhouse, voltiris, existing_pv, grid, gas_supply, ng_boiler, thermal_storage, battery)}
GENERAL = {m.ID: m for m in (commercial, subsidies, ems)}
OWNERS = {key: m.OWNS for key, m in {**BLOCKS, **GENERAL}.items()}   # who owns which parameters, for the overrides
REQUIRED = ("greenhouse", "grid")
NEEDS = {"ng_boiler": ["gas_supply"], "thermal_storage": ["ng_boiler"]}   # a block that cannot run without another


def business_model_of(case: dict) -> str:
    """The case's business model: general.commercial, else (older system cases) the Voltiris block's."""
    return (((case.get("general") or {}).get("commercial") or {}).get("business_model")
            or ((case.get("blocks") or {}).get("voltiris") or {}).get("business_model") or "direct_sales")
TIME_COLUMNS = {"month": "Month", "day": "Day", "hour": "Hour", "minute": "Minute"}
DT = timeseries.MODEL_STEP_MIN / 60


def column_names(block: str, columns: dict | None = None) -> dict:
    """Role -> column name for one block's file: the time columns and the block's own, renamed by `columns`."""
    return {**TIME_COLUMNS, **{c["role"]: c["column"] for c in BLOCKS[block].COLUMNS}, **(columns or {})}


def read_table(df: pd.DataFrame, year: int, names: dict, kinds: dict) -> tuple[pd.DataFrame, dict]:
    """The rows of one input file on a time index ("timestamp") built from Month, Day, Hour, Minute and the year (as
    the reference engine/inputs.py does), at 15 min. kinds: column -> power, energy, price or state, for a coarser
    file. Returns the table and the step found in the file."""
    m, d, h, mi = (names[k] for k in ("month", "day", "hour", "minute"))
    has_minute = mi in df.columns
    df = df.dropna(subset=[m, d, h, mi] if has_minute else [m, d, h]).reset_index(drop=True)
    df["timestamp"] = pd.to_datetime(dict(year=year, month=df[m], day=df[d], hour=df[h],
                                          minute=df[mi] if has_minute else 0))
    df = df.set_index("timestamp")
    info = timeseries.step_info(df.index)
    if info["step_minutes"] == timeseries.MODEL_STEP_MIN:
        return df, info
    data = [c for c in kinds if c in df.columns]
    out = timeseries.to_model_step(df[data].reset_index(drop=True), df.index, {c: kinds[c] for c in data})
    out.index.name = "timestamp"
    return out, info


def read_inputs(case: dict, read) -> tuple[pd.DatetimeIndex, dict, dict]:
    """Every chosen block's columns, on the greenhouse load's time stamps: (index, role -> series, block -> step
    info). read(path) gives a file's first sheet."""
    blocks, year = case["blocks"], case.get("year", case["market"]["year"])
    index, inputs, steps = None, {}, {}
    for key, module in BLOCKS.items():
        cfg = blocks.get(key)
        if cfg is None or not module.COLUMNS:
            continue
        if not cfg.get("input_file"):
            # only a block whose columns are all optional may have no file (the grid's day-ahead price, the gas
            # price): the block says itself if it needs it
            if any(c["needed"] == "always" for c in module.COLUMNS):
                raise KeyError(f"The {key} block has no input_file.")
            continue
        names = column_names(key, cfg.get("columns"))
        table, steps[key] = read_table(read(cfg["input_file"]), year, names,
                                       {names[c["role"]]: c["kind"] for c in module.COLUMNS})
        if index is None:
            index = table.index
        elif not table.index.equals(index):
            missing = int((~index.isin(table.index)).sum())
            if missing:
                raise ValueError(f"The {key} file ({cfg['input_file']}) misses {missing} of the "
                                 f"{len(index)} time steps of the greenhouse load file.")
            table = table.reindex(index)
        for c in module.COLUMNS:
            if names[c["role"]] in table.columns:
                inputs[c["role"]] = table[names[c["role"]]]
            elif c["needed"] == "always":   # the others: the block says itself when it needs them
                raise KeyError(f"Column '{names[c['role']]}' ({c['about']}) is missing in {cfg['input_file']}. "
                               f"Available columns: {list(table.columns)}")
    return index, inputs, steps


class System:
    def __init__(self, index: pd.DatetimeIndex, inputs: dict, market: dict, blocks: dict,
                 overrides: dict | None = None, business_model: str = "direct_sales", dt: float = DT,
                 one_meter: bool = True):
        not_built = sorted(set(blocks) - set(BLOCKS))
        if not_built:
            raise ValueError(f"Not built yet: {', '.join(not_built)}. The blocks that run are {', '.join(BLOCKS)}.")
        missing = [b for b in REQUIRED if b not in blocks]
        if missing:
            raise ValueError(f"A system needs {', '.join(REQUIRED)}; missing: {', '.join(missing)}.")
        for block, needed in NEEDS.items():
            lacking = [x for x in needed if block in blocks and x not in blocks]
            if lacking:
                raise ValueError(f"The {block} block needs {', '.join(lacking)} in the system.")
        self.market, self.dt, self.index = market, dt, index
        self.chosen = [b for b in BLOCKS if b in blocks]
        owned = P.split_overrides(overrides, OWNERS)
        fx = P.fx_rates()

        grid_params = grid.load_params(market, owned["grid"], fx)
        self.currency = grid_params["tariff"]["currency"]
        # the physical blocks
        gh = blocks["greenhouse"] or {}
        self.heat_blocks = [b for b in ("ng_boiler",) if b in blocks]   # the blocks that supply heat and CO2
        if self.heat_blocks:
            lacking = [c for c in ("heat_kw", "co2_kg_h") if c not in inputs]
            if lacking:
                names = {c["role"]: c["column"] for c in greenhouse.COLUMNS}
                raise KeyError(f"The greenhouse file needs the columns {', '.join(names[c] for c in lacking)} "
                               f"when the system has a heat block ({', '.join(self.heat_blocks)}).")
        self.greenhouse = greenhouse.Greenhouse(
            greenhouse.load_params(market, self.currency, owned["greenhouse"], fx), inputs["load_kw"], dt,
            inputs.get("heat_kw") if self.heat_blocks else None, inputs.get("co2_kg_h") if self.heat_blocks else None,
            gh.get("co2_mode", "required"))
        v = blocks.get("voltiris")
        self.voltiris = None if v is None else voltiris.Voltiris(
            voltiris.load_params(market, self.currency, owned["voltiris"], fx), inputs["pv_w_per_module"],
            int(v.get("modules", 0)))
        self.existing_pv = existing_pv.ExistingPV(inputs["existing_pv_kw"]) if "existing_pv" in blocks else None
        g = blocks["grid"] or {}
        self.grid = grid.Grid(grid_params, index, dt, inputs.get("day_ahead_eur_kwh"),
                              g.get("import_max_kw"), g.get("export_max_kw"))
        self.gas = None if "gas_supply" not in blocks else gas_supply.GasSupply(
            gas_supply.load_params(market, self.currency, owned["gas_supply"], fx), index,
            inputs.get("gas_price_eur_kwh"), grid_params["tariff"].get("eur_to_local", 1.0))
        self.boiler = (ng_boiler.Boiler(ng_boiler.load_params(market, self.currency, owned["ng_boiler"], fx))
                       if "ng_boiler" in blocks else None)
        self.boiler_kw = None   # the boiler's size: set by its study, then fixed for the other studies
        self.storage = (thermal_storage.ThermalStorage(
            thermal_storage.load_params(market, self.currency, owned["thermal_storage"], fx), index,
            inputs.get("outside_temp_c")) if "thermal_storage" in blocks else None)
        self.storage_kwh = None   # the heat storage's size: set by its study (none before it: no storage)
        self.battery = (battery.Battery(battery.load_params(market, self.currency, owned["battery"], fx))
                        if "battery" in blocks else None)
        # the general items
        self.commercial = commercial.Commercial(
            commercial.load_params(market, self.currency, business_model, owned["commercial"], fx))
        self.subsidies = subsidies.Subsidies(subsidies.load_params(market, self.currency, owned["subsidies"], fx),
                                             self.greenhouse.yearly_load_kwh)
        self.ems = ems.Ems(ems.load_params(market, self.currency, owned["ems"], fx)["ems"])

        # what the blocks give together: the site's PV behind one meter, as in the reference model
        self.load = self.greenhouse.load
        self.modules = self.voltiris.modules if self.voltiris else 0
        self.volt_pv = self.voltiris.pv if self.voltiris else self.load * 0.0
        self.existing = self.existing_pv.pv if self.existing_pv else None
        self.pv_total = self.volt_pv + self.existing if self.existing is not None else self.volt_pv
        self.bm = self.commercial.business_model(self.modules, self.volt_pv, self.pv_total, self.grid.export_price(), dt)
        self.pv_life_yr = self.commercial.pv_life_yr   # the horizon of the payback and of battery replacements
        self.one_meter = one_meter   # no import and export in the same step, exact where it could pay (dispatch)
        self.battery_export = self.grid.battery_export

    def import_price(self, regime: str) -> pd.Series:
        return self.grid.import_price(regime)

    @property
    def eta2(self) -> float:
        """The battery's round trip (1 without a battery)."""
        return self.battery.tech.eta2 if self.battery else 1.0

    # -- money that joins a block and the general items --------------------------------------------------------------
    def battery_net_capex(self, size_kwh: float) -> float:
        """The battery's first purchase after its subsidy (without the EMS hardware)."""
        return self.subsidies.battery_net(size_kwh, self.commercial.battery_gross)

    def battery_investment(self, size_kwh: float) -> float:
        """What the grower pays up front for the battery: net battery price + EMS hardware."""
        return self.battery_net_capex(size_kwh) + self.ems.capex

    def ancillary_revenue(self, size_kwh: float) -> float:
        """Yearly revenue of the battery's reserved power."""
        return self.battery.tech.ancillary_revenue(size_kwh, self.commercial.ancillary_rate)


def parameters(market: dict, business_model: str = "direct_sales", overrides: dict | None = None) -> dict:
    """Every block's and general item's parameters for a market in one dict (the reference model's layout), money in
    the market's currency, overrides applied."""
    owned = P.split_overrides(overrides, OWNERS)
    fx = P.fx_rates()
    out = grid.load_params(market, owned["grid"], fx)
    currency = out["tariff"]["currency"]
    for part in (greenhouse.load_params(market, currency, owned["greenhouse"], fx),
                 voltiris.load_params(market, currency, owned["voltiris"], fx),
                 gas_supply.load_params(market, currency, owned["gas_supply"], fx),
                 ng_boiler.load_params(market, currency, owned["ng_boiler"], fx),
                 thermal_storage.load_params(market, currency, owned["thermal_storage"], fx),
                 battery.load_params(market, currency, owned["battery"], fx),
                 commercial.load_params(market, currency, business_model, owned["commercial"], fx),
                 subsidies.load_params(market, currency, owned["subsidies"], fx),
                 ems.load_params(market, currency, owned["ems"], fx)):
        out = P.deep_merge(out, part)
    return out


# -- case files ------------------------------------------------------------------------------------------------------
def from_battery_case(case: dict) -> dict:
    """A reference case file as a system case: every block reads the case's one workbook. The blocks are
    case["system"]["blocks"] when an earlier interface wrote them, else greenhouse + Voltiris (pv_modules, 0
    included) + grid + battery, with existing PV when use_existing_pv is true."""
    chosen = (case.get("system") or {}).get("blocks")
    chosen = set(chosen) if chosen else ({"greenhouse", "voltiris", "grid", "battery"}
                                         | ({"existing_pv"} if case.get("use_existing_pv") else set()))
    data = {"input_file": case.get("input_file")}
    if case.get("columns"):
        data["columns"] = case["columns"]
    blocks: dict = {b: {} for b in chosen}
    for key in blocks:
        if key in BLOCKS and BLOCKS[key].COLUMNS:
            blocks[key] = dict(data)
    if "voltiris" in blocks:
        blocks["voltiris"]["modules"] = case.get("pv_modules", 0)
    if "grid" in blocks:
        blocks["grid"].update({**(case.get("grid") or {}), "regime": case.get("regime") or {}})
    if "battery" in blocks:
        blocks["battery"] = {"sizing": case.get("sizing")}
    out = {k: case[k] for k in ("year", "market", "overrides", "tag", "output_dir", "system") if k in case}
    out["blocks"] = blocks
    out["general"] = {"commercial": {"business_model": case.get("business_model", "direct_sales")}}
    return out


def as_system_case(case: dict) -> dict:
    return case if "blocks" in case else from_battery_case(case)


def with_paths(case: dict, case_dir: Path) -> dict:
    """The case with every block's input_file made absolute (relative paths are relative to case_dir)."""
    out = dict(case, blocks={k: dict(v or {}) for k, v in case["blocks"].items()})
    for cfg in out["blocks"].values():
        if cfg.get("input_file") and not Path(cfg["input_file"]).is_absolute():
            cfg["input_file"] = str((Path(case_dir) / cfg["input_file"]).resolve())
    return out


def load_case(path: Path) -> dict:
    """A case file (either format) as a system case, its input files made absolute."""
    path = Path(path)
    case = json.loads(path.read_text(encoding="utf-8"))
    if "market" not in case:
        raise KeyError("The case file has no 'market'.")
    if "blocks" not in case and "input_file" not in case:
        raise KeyError("The case file has neither 'blocks' nor 'input_file'.")
    return with_paths(as_system_case(case), path.parent)


def market_of(case: dict) -> dict:
    m = case["market"]
    return {**m, "region": m.get("region", m.get("canton"))}


def excel_reader():
    """read(path): the file's first sheet, each file read once."""
    cache: dict = {}

    def read(path):
        key = str(Path(path).resolve())
        if key not in cache:
            cache[key] = pd.read_excel(key)
        return cache[key]
    return read


def from_tables(case: dict, read) -> System:
    """The system of a case (either format, input files absolute) with read(path) giving each file's first sheet."""
    case = as_system_case(case)
    index, inputs, _ = read_inputs(case, read)
    return System(index, inputs, market_of(case), case["blocks"], case.get("overrides"), business_model_of(case))


def build(case: dict, case_dir: Path) -> System:
    """The system of a case, reading its input files (relative to case_dir or absolute)."""
    return from_tables(with_paths(as_system_case(case), case_dir), excel_reader())


# -- the reference model's view of a system case -------------------------------------------------------------------
REFERENCE_COLUMNS = {"load_kw": "Loadcurve (kW)", "pv_w_per_module": "Production voltiron (W)",
                     "existing_pv_kw": "Current PV feed-in (kW)", "day_ahead_eur_kwh": "Day ahead kWh"}


def reference_frame(case: dict, read) -> pd.DataFrame:
    """The system's inputs as one workbook in the reference model's format (its default column names, 15 min), so
    elements/battery_reference can run the same case. Without Voltiris the yield column is 0 (0 modules)."""
    index, inputs, _ = read_inputs(as_system_case(case), read)
    out = pd.DataFrame({"Month": index.month, "Day": index.day, "Hour": index.hour, "Minute": index.minute})
    for role, name in REFERENCE_COLUMNS.items():
        if role in inputs:
            out[name] = inputs[role].values
        elif role == "pv_w_per_module":
            out[name] = 0.0
    return out


def to_battery_case(case: dict) -> dict:
    """A system case as a reference case (without input_file: the caller writes reference_frame())."""
    b = case["blocks"]
    v, g = b.get("voltiris"), b.get("grid") or {}
    out = {"year": case.get("year", case["market"]["year"]), "market": case["market"],
           "business_model": business_model_of(case),
           "pv_modules": (v or {}).get("modules", 0) if v is not None else 0,
           "use_existing_pv": "existing_pv" in b,
           "grid": {k: g[k] for k in ("import_max_kw", "export_max_kw") if k in g},
           "regime": g.get("regime") or {"auto": True},
           "sizing": (b.get("battery") or {}).get("sizing"),
           "overrides": case.get("overrides") or {}}
    for k in ("tag", "output_dir"):
        if k in case:
            out[k] = case[k]
    return {k: v for k, v in out.items() if v is not None}
