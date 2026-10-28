# The blocks, their inputs, and an example of each

Each block reads its own input file. The data here is synthetic, cut from `examples/battery` (the reference model's
example workbook): the numbers mean nothing, no real site is behind them.

## What every input file looks like

- An Excel workbook; the first sheet is read.
- One row per time step, with the columns `Month`, `Day`, `Hour` and, for steps shorter than an hour, `Minute`. The
  case's `year` completes the time stamp; a time stamp marks the start of its step (hour 13 covers 13:00 to 14:00).
- 15-minute steps, or a coarser step (hourly, 30 min) that is converted when the system runs: kW, W and prices are
  repeated in each quarter hour, kWh per step would be divided.
- The greenhouse load file sets the run's time steps; every other file must cover all of them.
- Other column names are allowed: give them in the case under the block's `columns`, e.g.
  `"columns": {"load_kw": "Load (kW)", "minute": "Min"}`, or pick them in the interface.

## The blocks

| Block | Input file: column (default name), unit | Settings in the case file | Parameter files |
|---|---|---|---|
| Greenhouse demand (`greenhouse`) | site electricity load (`Loadcurve (kW)`), kW average per step; required | none | none yet |
| Voltiris (`voltiris`) | yield of one module (`Production voltiron (W)`), W per module; required | `modules` (count) | `elements/voltiris/params`: module Wp |
| Existing PV (`existing_pv`) | output of the PV already on site (`Current PV feed-in (kW)`), kW; required | none | none (not sized, cost sunk) |
| Grid (`grid`) | day-ahead price (`Day ahead kWh`), EUR/kWh; only for tariffs priced on it (NL, FR) | `import_max_kw`, `export_max_kw` (missing = automatic), `regime` (`{"auto": true}` or `{"auto": false, "manual": "B"}`); the case's `market` | `elements/grid/params/tariffs/<country>/<region>/<utility>_<year>.json` and the country and region files |
| Battery (`battery`) | none | `sizing`: `objective` (`profit`, `payback`, `custom`), `sweep_kwh`, `custom_kwh`, `fine_grid_kwh`, `fine_window_kwh`, `cap_at_subsidy_size` | `elements/battery/params`: technology, the ancillary reserve per country |

The general items need no input file; their values are parameter files, changed for one run with the overrides:

| General item | Setting in the case file | Parameter files |
|---|---|---|
| Market | `market` (country, region, utility, year); sets the run's currency | the grid's tariff files |
| Commercial | `general.commercial.business_model` (`direct_sales` or `eaas`) | `general/commercial/params`: business models (EaaS price), Voltiris price per Wp, battery price tiers and replacements, PV and battery lives, ancillary revenue rate per country |
| Subsidies | none | `general/subsidies/params`: Voltiris and battery subsidies per country and region |
| EMS | none | `general/ems/params`: fixed cost, hardware, fees |

Greenhouse and grid are required in every system. Voltiris and existing PV must run and are added together as one PV
generator behind the site's meter, as in the reference model. The blocks not listed here are not built yet
(`common/blocks.json`, `PLAN.md`).

## The example files

| File | Block | Step | Content |
|---|---|---|---|
| `greenhouse_load_2026.xlsx` | greenhouse | 15 min, 35,040 rows | `Loadcurve (kW)`, about 1,518 MWh a year |
| `voltiris_yield_2026.xlsx` | voltiris | 15 min, 35,040 rows | `Production voltiron (W)`, about 163 kWh per module a year |
| `existing_pv_2026_hourly.xlsx` | existing_pv | hourly, 8,760 rows | `Current PV feed-in (kW)`: the Voltiris yield of 150 modules, averaged per hour (synthetic), about 24 MWh a year; no `Minute` column |
| `grid_day_ahead_2026.xlsx` | grid | 15 min, 35,040 rows | `Day ahead kWh`, EUR/kWh |

The battery has no file: its example is the `battery` entry of the case files.

| Case file | Market | Blocks |
|---|---|---|
| `case_blocks_CH.json` | CH, SIG | greenhouse, Voltiris (500 modules, direct sales), grid, battery (100 and 200 kWh) |
| `case_blocks_NL.json` | NL, Westland Infra | the same |
| `case_blocks_FR.json` | FR, TURPE 7 HTA | the same |
| `case_blocks_CH_existing_pv.json` | CH, SIG | the same, plus existing PV from the hourly file |

The first three hold the same data as `examples/battery` and give the same results as those cases.

## Run

From the project folder:

    python system/run_case.py examples/blocks/case_blocks_CH.json        (writes the results next to the case)
    python system/compare.py examples/blocks/case_blocks_CH.json         (the blocks and the reference model, compared)
    python interface/app.py                                              (pick a case on the System page)

Checked on 28 Oct 2026: the four cases give the same results with the blocks and with the reference model, to the
last digit.
