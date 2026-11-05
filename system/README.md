# system: the engine for the blocks

```
python system/run_case.py case.json            run a case with the blocks
python system/compare.py case.json [more]      run cases with the battery sweep and the reference model, compare
python -m pytest system/tests -q               checks (about 10 min)
```

## Files

```
setup.py       the case (both formats), each block's input file read and aligned, the System of the chosen blocks,
               and the reference model's view of a case (one workbook, its case format)
dispatch.py    the network from the blocks, the rules that join two blocks, the solve, the dispatch tables
               (electricity; heat, CO2 and gas, heat storage)
electricity.py the electricity side of every run: supply and demand, self-consumption, the bill without and with
               PV, without battery and with the chosen battery, and what the PV and the battery save, flow by flow
joint.py       joint sizing: every sized block's size a variable of one optimisation, for the site's lowest yearly
               cost (with a battery, also without it, for its EMS check)
costs.py       the site's yearly cost: running (grid, gas, levy, O&M, EMS, less revenues) and investments per year
effects.py     with and without each technology: the system without it sized again together, line by line
technical.py   each piece of equipment at its size (how the size was found, what one more unit costs per year, how
               hard it works) and the year's energy (electricity, heat, CO2, gas); no solve
sensitivity.py each size -10 % and +10 %, the year's operation solved again (no re-sizing)
battery_check.py the battery sized again by the reference sweep, against its joint size
flows.py       bills, self-consumption and self-sufficiency, monthly table, value split (the reference's flows.py)
run_case.py    the command line: the run of a case in the order below, written as summary_<tag>.json and
               results_<tag>.xlsx
compare.py     the same case files through elements/battery_reference and through the blocks' battery sweep
               (elements/battery/study.py)
tests/         parameters as the reference, a subsidy's amount kept as a setting, overrides routing, blocks not
               built or missing, separate input files, electricity balance, short studies as the reference, daily
               gas price to 15 min, heat and CO2 balance, boiler covering, heat storage balance and loss models,
               electricity split, joint sizing, a run with nothing to size, links between blocks, the battery sized
               together with its check and the sensitivity, external CO2, a technology kept when it is the only
               source, savings per flow, heat pump, a size fixed at 0
```

## Sizing

The sized blocks are the gas boiler (kW of heat), the heat pump (kW of heat), the heat storage (kWh of heat) and the
battery (kWh bought). They are always sized together (`joint.py`): every free size is a variable of one optimisation
(PyPSA capacity expansion) that minimises the site's yearly cost: running costs + each investment / its life +
fixed O&M - the battery's ancillary revenue. A block that lets another be smaller counts for it (a heat storage that
shaves the boiler's peak). A block's `"sizing": {"objective": "custom", "custom_kw"/"custom_kwh": X}` fixes its size
(0: not installed); anything else leaves it to the model. What is exact and what is approximated (the battery's
price, EMS, regime) is in the module's docstring; a battery it sizes is kept only if the site is still cheaper with
its EMS costs. Without the subsidy cap (`cap_at_subsidy_size`), the largest size of the battery's `sweep_kwh` is the
joint sizing's upper limit.

The run (`run_case.py`), technical results before the money:

1. joint sizing (`joint.py`);
2. each block's year at its size, for its own tables: the boiler (`elements/ng_boiler/study.py`; none at size 0),
   the battery (`elements/battery/study.py` at the joint size), the heat pump (from the site's year); and the
   electricity side (`electricity.py`), also for a system with nothing to size;
3. every technology with and without it (`effects.py`): the system without it, and without what cannot run without
   it, sized again together and set against the system with it; the heat storage's tables come from this
   (`elements/thermal_storage/study.py`, `from_joint`). A technology is not evaluated when leaving it out would leave
   the heat or CO2 demand without a source;
4. the site's yearly cost (`costs.py`);
5. the technical summary (`technical.py`): per piece of equipment, its size, how it was found (given, optimised,
   fixed in the case, optimised: not worth installing), the yearly cost of one more unit (investment / life + fixed
   O&M; the battery: first purchase after subsidy and replacements over the PV life, less ancillary, per kWh
   bought), the energy it gives and its share of the demand, full-load hours (cycles for storage) and hours at full
   size (at least 99 % of its size); and the year's energy table (electricity, heat, CO2, gas);
6. sensitivity (`sensitivity.py`): each installed sized block and the Voltiris modules at -10 % and +10 % of its
   size, everything else at its chosen size, the year's operation solved again (no re-sizing) under the joint
   sizing's regime: yearly cost (EMS from the joint sizing's bill without battery) and key figures (grid import,
   self-sufficiency, gas, CO2 emitted, heat and CO2 unmet). Unmet heat or CO2 is not priced, so a smaller size that
   leaves demand unmet can look cheaper. 1 + 2 x (number of equipment) solves. `"system": {"sensitivity": false}`
   skips it;
7. battery check (`battery_check.py`), when the model sizes the battery: the battery sized again by the reference
   sweep (`elements/battery/study.py`, the battery's case settings `sweep_kwh`, `objective` profit or payback,
   `fine_grid_kwh`, `cap_at_subsidy_size`) with the other blocks at their joint sizes, set against its joint size:
   size, yearly value, first purchase, payback, lifetime profit (the sweep's objective), battery per year over the PV
   life, site yearly cost (the joint sizing's objective). The two rules differ, so the sizes may too.
   `"system": {"battery_check": false}` skips it.

The formulas of every step are in `OPTIMISATION.md`.

## Links between blocks

`common/blocks.json` says which blocks depend on others: `fixed` (greenhouse and grid, always in), `needs` (the gas
boiler needs the gas supply), `needs_one_of` (a heat storage needs a heat source) and `follows` (the gas supply is in
exactly when a block that burns gas is). `setup.py` refuses a system that breaks the first three; the interface
applies all four when blocks are clicked. `setup.leave_out()` takes blocks out with what can no longer run without
them (with and without each technology).

The heat pump links heat and electricity: its electricity is part of the site's load, so its size, the battery's and
the boiler's are weighed against each other in the joint sizing, and the battery's own study counts the gas and CO2
it saves by changing when the heat pump runs (A24). Without a heat pump the battery does not change the heat side.

## Heat side

Added to the network only when the system has a heat or CO2 source (the gas boiler, the heat pump, external CO2), so
a system without one gives the reference's LP. The CO2 bus comes with any CO2 source, the heat bus with any heat
source, the gas bus with the boiler:

| Bus | Components |
|---|---|
| `gas` | `gas_supply` (generator, cost = gas price + levy x emission factor) |
| `heat` | `heat_demand` (load), `heat_unmet` (penalised slack), `boiler` (link output), `heat_pump` (link from `main`, efficiency = the COP of each step), `heat_release` (free sink), `heat_charger` and `heat_discharger` (links to the storage's own bus `heat_store_bus` with the store `heat_store`) |
| `co2` | `co2_demand` (load) and `co2_unmet` (penalised slack) when the CO2 demand must be met, `boiler` (second output), `co2_bought` (external CO2, at its price), `co2_vent` (free sink) |

Heat, CO2 and gas balance at every step (tested). In the joint sizing the heat demand has no slack when a heat
source's size is free, and the CO2 demand none when the boiler's is: they must be met. With a heat pump, the site's
load in the results is the greenhouse load + the heat pump's draw (`results()` gives both apart). Under EaaS the PV
surplus runs the heat pump first and the site imports only what it draws beyond it (time sharing within the step);
the rules fixed before the solve that still use the greenhouse load are listed in thesis.md A23.

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
    "ng_boiler": {"sizing": {"objective": "custom", "custom_kw": 1350}},
    "battery": {"sizing": {"objective": "profit", "sweep_kwh": [100, 200]}}
  },
  "general": {"commercial": {"business_model": "direct_sales"}},
  "system": {"sensitivity": true, "battery_check": true},
  "overrides": {"tech": {"battery": {"c_rate": 0.4}}}
}
```

- `general` holds the general items' settings (`general/README.md`); commercial, subsidies and EMS are always part of
  the system, and the `System` joins them with the blocks (battery net price, investment, ancillary revenue).
- `system`: `sensitivity` and `battery_check` (both default on, above); the interface also writes its `preset` and
  `run_type` there. A `sizing` key is no longer read.
- A sized block's `sizing`: `{"objective": "custom", "custom_kw"/"custom_kwh": X}` fixes its size, anything else (or
  nothing) leaves it to the joint sizing. The battery's other settings drive the battery check.

- A block not listed is not in the system; greenhouse and grid are required. Blocks may share a file.
- `input_file` is relative to the case file or absolute; `columns` under a block renames its columns.
- The greenhouse load file sets the run's time steps; a coarser file (hourly, 30 min) is brought to 15 min, and every
  file must cover the load file's time steps. What each block reads: `examples/blocks/README.md`.
- `overrides` keep the reference layout and each value goes to the block or general item that owns it (`OWNS`).
- A reference case file (one `input_file`, no `blocks`) is read as the same system: every block reads that workbook.
- For the reference model, a system case becomes one workbook in its format (`reference_frame`) and its case format
  (`to_battery_case`): that is how `compare.py` and the interface's reference run type run it.

## Check against the reference (28 Oct 2026)

`compare.py` runs the reference model and the blocks' battery sweep (`elements/battery/study.py`, the battery check's
rule) and compares the summary and every table cell by cell. All identical to the last digit:

| Cases | |
|---|---|
| `examples/battery`: CH, NL, FR, one workbook | identical |
| `examples/blocks`: CH, NL, FR and CH with existing PV (hourly file), one file per block | identical |
| variants: CH EaaS, CH with existing PV, CH 0 modules, CH custom size with a fine grid, NL with ancillary off and overrides (C-rate, price tiers, module Wp, PV life), FR manual regime CU with `battery_export: any` and payback objective, FR EaaS | identical |

The interface was checked too: the examples run through the page with either model give the same files. Checked
again on 4 Nov 2026, after sizing became always joint: still identical on `examples/battery` CH, FR, NL and
`examples/blocks` CH.

## Not built yet

Comparing scenarios (Baseline against S1 to S4, `PLAN.md` section 4), and the emissions of the electricity bought
(today only the CO2 of the gas burnt is counted). Today the engine runs the joint sizing, each block's year at its
size, the electricity side and the site's yearly cost of every system, every technology with and without it, the
technical summary, the sensitivity and the battery check.
