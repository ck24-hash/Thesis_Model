# system: the engine for the blocks

```
python system/run_case.py case.json            run a case with the blocks
python system/compare.py case.json [more]      run cases with both models and compare
python -m pytest system/tests -q               checks (about 4 min)
```

## Files

```
setup.py       the case (both formats), each block's input file read and aligned, the System of the chosen blocks,
               and the reference model's view of a case (one workbook, its case format)
dispatch.py    the network from the blocks, the rules that join two blocks, the solve, the dispatch tables
               (electricity; heat, CO2 and gas, heat storage)
electricity.py the electricity side of every run: supply and demand, self-consumption, the bill without and with
               PV, without battery and with the chosen battery
joint.py       joint sizing: every sized block's size a variable of one optimisation, for the site's lowest yearly
               cost; then each block left out once for its value in the system
costs.py       the site's yearly cost: running (grid, gas, levy, O&M, EMS, less revenues) and investments per year
flows.py       bills, self-consumption and self-sufficiency, monthly table, value split (the reference's flows.py)
run_case.py    the command line: the sizing of a case (joint, or each block's study), the electricity side and
               the site's yearly cost, written as summary_<tag>.json and results_<tag>.xlsx
compare.py     the same case files through elements/battery_reference and through the blocks
tests/         parameters as the reference, overrides routing, separate input files, electricity balance, short
               studies as the reference, daily gas price to 15 min, heat and CO2 balance, boiler covering, heat
               storage balance and loss models, electricity split
```

## Sizing

The sized blocks are the gas boiler (kW of heat), the heat storage (kWh of heat) and the battery (kWh bought). The
case's `"system": {"sizing": ...}` says how:

- `joint` (default, with two sized blocks or more), `joint.py`: every free size is a variable of one optimisation
  (PyPSA capacity expansion) that minimises the site's yearly cost: running costs + each investment / its life +
  fixed O&M - the battery's ancillary revenue. A block that lets another be smaller counts for it (a heat storage
  that shaves the boiler's peak). Each block is then left out once and the others sized again: the cost difference
  is its value in the system. Each block's study then runs at its joint size for its own tables. What is exact and
  what is approximated (the battery's price, EMS, regime) is in the module's docstring; the battery is kept only if
  the site is still cheaper with its EMS costs.
- `sequential` (and always with one sized block): each block's study sizes it with the others fixed, in the order
  gas boiler (`elements/ng_boiler/study.py`, lifetime cost), heat storage (`elements/thermal_storage/study.py`, value
  against no storage), battery (`elements/battery/study.py`, the reference model's study). A battery-only case gives
  the reference model's results this way.

A block with the objective `custom` keeps its size in both. Then, always: the electricity side (`electricity.py`) and
the site's yearly cost (`costs.py`), also for a system with nothing to size.

Nothing links heat and electricity yet (no heat pump, CHP or electric heater), so today the joint sizing couples the
boiler and the heat storage, and the battery is sized in the same optimisation without changing them (A16).

## Heat side

Added to the network only when the system has a heat block (today the gas boiler), so a system without one gives
the reference's LP:

| Bus | Components |
|---|---|
| `gas` | `gas_supply` (generator, cost = gas price + levy x emission factor) |
| `heat` | `heat_demand` (load), `heat_unmet` (penalised slack), `boiler` (link output), `heat_release` (free sink), `heat_charger` and `heat_discharger` (links to the storage's own bus `heat_store_bus` with the store `heat_store`) |
| `co2` | `co2_demand` (load) and `co2_unmet` (penalised slack) when the CO2 demand must be met, `boiler` (second output), `co2_vent` (free sink) |

Heat, CO2 and gas balance at every step (tested). In the joint sizing the heat and CO2 demand have no slack when
the boiler's size is free: they must be met.

## Case file

The system format (`setup.py`), one input file per block:

```json
{
  "year": 2026, "tag": "blocks_CH",
  "market": {"country": "CH", "region": "GE", "utility": "SIG", "year": 2026},
  "blocks": {
    "greenhouse": {"input_file": "greenhouse_demand_2026.xlsx", "co2_mode": "required"},
    "voltiris": {"input_file": "voltiris_yield_2026.xlsx", "modules": 500},
    "existing_pv": {"input_file": "existing_pv_2026_hourly.xlsx"},
    "grid": {"input_file": "grid_day_ahead_2026.xlsx", "import_max_kw": 750, "export_max_kw": 750,
             "regime": {"auto": true}},
    "gas_supply": {"input_file": "gas_price_2026_daily.xlsx"},
    "ng_boiler": {"sizing": {"objective": "lifetime_cost"}},
    "battery": {"sizing": {"objective": "profit", "sweep_kwh": [100, 200]}}
  },
  "general": {"commercial": {"business_model": "direct_sales"}},
  "overrides": {"tech": {"battery": {"c_rate": 0.4}}}
}
```

- `general` holds the general items' settings (`general/README.md`); commercial, subsidies and EMS are always part of
  the system, and the `System` joins them with the blocks (battery net price, investment, ancillary revenue).

- A block not listed is not in the system; greenhouse and grid are required. Blocks may share a file.
- `input_file` is relative to the case file or absolute; `columns` under a block renames its columns.
- The greenhouse load file sets the run's time steps; a coarser file (hourly, 30 min) is brought to 15 min, and every
  file must cover the load file's time steps. What each block reads: `examples/blocks/README.md`.
- `overrides` keep the reference layout and each value goes to the block or general item that owns it (`OWNS`).
- A reference case file (one `input_file`, no `blocks`) is read as the same system: every block reads that workbook.
- For the reference model, a system case becomes one workbook in its format (`reference_frame`) and its case format
  (`to_battery_case`): that is how `compare.py` and the interface's reference run type run it.

## Check against the reference (28 Oct 2026)

`compare.py` runs both models and compares the summary and every table cell by cell. All identical to the last digit:

| Cases | |
|---|---|
| `examples/battery`: CH, NL, FR, one workbook | identical |
| `examples/blocks`: CH, NL, FR and CH with existing PV (hourly file), one file per block | identical |
| variants: CH EaaS, CH with existing PV, CH 0 modules, CH custom size with a fine grid, NL with ancillary off and overrides (C-rate, price tiers, module Wp, PV life), FR manual regime CU with `battery_export: any` and payback objective, FR EaaS | identical |

The interface was checked too: the examples run through the page with either model give the same files.

## Not built yet

The whole system's yearly cost and emissions in one place, comparable across scenarios (`PLAN.md` section 4).
Today the engine runs the gas boiler, heat storage and battery studies, and the electricity side of every system.
