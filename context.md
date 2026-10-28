# Context for Claude Code: the Voltiris battery model

Read this first. It explains what the project is, how the model works, how to run it, and what was changed or decided
in the work done with Claude on 23 to 28 Oct 2026. The detailed parameter documentation is in
`elements/battery_reference/README.md`; this file does not repeat every number.

## 1. What this project is

A techno-economic model that sizes a battery next to Voltiris PV (agrivoltaic modules on greenhouses) for one site
and one year, and computes its value and payback. It is Jesse's notebook `CH_fixed_battery_5.0_+PV_SIG`, split into an
engine and parameter blocks, with one parameter map per market:

| Market | `market` in a case file | Currency |
|---|---|---|
| CH, SIG (Geneva) | `{"country": "CH", "region": "GE", "utility": "SIG", "year": 2026}` | CHF |
| NL, Westland Infra MS | `{"country": "NL", "region": "WestlandInfra", "utility": "MS", "year": 2026}` | EUR |
| FR, TURPE 7 HTA, reference supplier | `{"country": "FR", "region": "HTA", "utility": "Reference", "year": 2025}` | EUR |

The folder was extracted from the Pre-feasibility repo (`Voltiris/prefeasibility`). Everything not related to the
battery model was removed (see section 8). The goal is to build on it with other blocks into a larger model.

Since 28 Oct 2026 this model is the frozen reference (`elements/battery_reference`). It has been split into blocks
(`elements/greenhouse`, `voltiris`, `existing_pv`, `grid`, `battery`), general items (`general/commercial`,
`subsidies`, `ems`) and an engine (`system/`) that give the same results; new work goes there (`PLAN.md`, `elements/README.md`, `system/README.md`). This file still describes the
reference, and its rules (section 5) hold for the blocks too.

## 2. Folder layout

```
README.md                    install, run, where things are
context.md                   this file
elements/battery_reference/  the model, frozen (moved from models/battery on 28 Oct 2026)
  run_case.py                command line: load_case(), setup_from_case(), write_results(), main()
  parameters.py              load(country, region, utility, year, business_model, overrides) -> params dict
  case_template.json         a blank case file
  requirements.txt           pypsa 1.3.0, linopy 0.9.1, highspy, pandas 3.0.5, numpy 2.5.2, openpyxl, pytest
  engine/                    inputs.py, setup.py, dispatch.py, sizing.py, flows.py, pipeline.py
  blocks/                    tariffs.py, tech.py, capex.py, subsidies.py, ems.py, business_model.py, finance.py
  params/                    the numbers as JSON (see 4.2)
  tests/test_battery.py      35 tests on invented numbers
elements/<block>/            the same model split into blocks (elements/README.md)
system/                      the engine for the blocks, run_case.py and compare.py (system/README.md)
interface/                   browser interface for every run type, both battery studies included (section 6)
common/                      time step conversion, parameters and money, block list, scenario presets
examples/battery/            synthetic input workbook + case files for CH, FR and NL, and a README
```

## 3. How to run

Python 3.12 or 3.13, one virtual environment, run from the project root:

```
pip install -r elements/battery_reference/requirements.txt
python elements/battery_reference/run_case.py examples/battery/case_example_CH.json     # one study, results next to the case
python interface/app.py                                                     # browser interface, http://127.0.0.1:8775
python -m pytest elements/battery_reference/tests -q                                    # 35 tests, about 1 min
```

The command line writes `summary_<tag>.json` and `results_<tag>.xlsx` next to the case file (or to `output_dir`).
Running an example case therefore writes result files into `examples/battery/`.

## 4. How the model works

### 4.1 Inputs

**Workbook** (first sheet, one row per 15 minutes, 35,040 rows for a year). Default column names, renamable with
`columns` in the case file (`engine/inputs.py` DEFAULT_COLUMNS):

| Column | Meaning |
|---|---|
| `Month`, `Day`, `Hour`, `Minute` | time stamp, with the case's `year` |
| `Loadcurve (kW)` | site load |
| `Production voltiron (W)` | yield of ONE Voltiris module, W; multiplied by `pv_modules` |
| `Current PV feed-in (kW)` | existing PV, used only with `use_existing_pv: true` |
| `Day ahead kWh` | day-ahead price, EUR/kWh; required by NL and FR (converted to CHF for CH if used) |

**Case file** (JSON, keys documented at the top of `run_case.py`): `input_file` and `market` are required; optional
`year`, `columns`, `business_model` (`direct_sales` or `eaas`), `pv_modules`, `use_existing_pv`, `grid`
(`import_max_kw`, `export_max_kw`; missing = automatic: 2 x max load, 1.1 x max PV), `regime` (`{"auto": true}` or
`{"auto": false, "manual": "B"}`), `sizing`, `overrides`, `tag`, `output_dir`.

### 4.2 Parameters (`parameters.py`, `params/`)

```
params/tariffs/<country>/_country.json                         currency, national levies, export basis
params/tariffs/<country>/<region>/_canton.json or _region.json canton (CH), grid area (NL), voltage level (FR)
params/tariffs/<country>/<region>/<utility>_<year>.json        utility / grid operator / supplier
params/subsidies/<country>/_country.json, <region>.json
params/ancillary/<country>.json                                reserve share and rate (always applied, see 4.6)
params/tech|capex|finance|ems/default.json                     same everywhere; <country>.json overrides
params/business_models/direct_sales.json, eaas.json
params/fx.json                                                 1 CHF = 1.09 EUR
```

The more specific file wins (deep merge). Shared money values are written `{"amount": x, "currency": "CHF"}` (or
`{"tiers": [[kWh, price], ...], "currency": ...}`) and converted to the market's currency, so every country pays the
same real price. Case `overrides` change single values for one study, in the market's currency; an unknown block
name raises a KeyError. `_about` and `*_note` keys are documentation.

### 4.3 One study (`engine/pipeline.py` run())

1. **Regime**: CH picks A or B from the DUP of the grid draw without battery (DUP = yearly import kWh / yearly HP
   peak kW; at or below 3,000 h is A, above is B). FR uses the case's TURPE option (LU default, or CU). NL has one.
2. **Year without battery**: solved by the same LP; its total cost is the baseline every size is compared with.
3. **Size sweep** (`engine/sizing.py`): each size is solved for the whole year (section 4.4) and valued (4.5); then
   one size is chosen.
4. **Chosen size**: its dispatch (kept from the sweep), its bill, SC/SS, monthly table, and the value split into
   energy savings (self-consumption, arbitrage), peak shaving (capacity charges saved + regime switch), ancillary
   revenue and EMS costs.
5. **Payback table**: Voltiris PV saving (bill with existing PV only vs with Voltiris), battery cost over the 25-year
   PV life (replacements), and payback scenarios with and without subsidies.
6. The summary (about 55 values + the sweep) and the tables; `run_case.write_results()` writes them.

### 4.4 The dispatch LP (`engine/dispatch.py`)

One PyPSA network per solve, one bus, 35,040 quarter hours, perfect foresight, solved with HiGHS (dual simplex,
default settings, `io_api="direct"`).

- PV must run (no curtailment). Load is fixed. Grid import at the tariff's price per step; grid export at the export
  value (fixed or day-ahead; under EaaS the Voltiris share is handled by the business model).
- Battery: a Store plus a charge Link and a discharge Link. Store size = SoC window (10 to 90% of the bought size)
  minus the ancillary reserve; link power = size x C-rate (0.5) minus the reserved power. Efficiencies 97% each way,
  0.1%/day self-discharge, cyclic over the year.
- `_extra()` adds to the objective: capacity charges (monthly HP peak with annual ratchet for CH; yearly peak +
  monthly peak for NL; the TURPE staircase pointe >= HPH >= HCH >= HPB >= HCB for FR), the optional DUP lock (keeps
  DUP inside a regime), and the one-meter rules.
- **One meter** (only where cheating could pay: export worth more than import, or a negative price): with shortfall
  D = (load - PV)+, surplus S = (PV - load)+, power P, discharge efficiency eta:
  import <= D + max(1 - S/P, 0) x charging; export <= S + max(eta - D/P, 0) x discharging;
  charging + discharging <= P. Linear, so it stays an LP. Binary switches were tried and dropped (20+ min per size,
  within 0.02%). CH never meets these cases.
- **PV-only battery export** (FR, `battery_export: "pv_only"`): the battery keeps an account of its PV energy; only
  PV energy may be exported, grid energy only serves the site. No tie-break term in the objective: a 1e-6 one made a
  French year about 50 times slower.
- `results()` returns the dispatch table in kW: load, pv, grid_import, grid_export (positive), battery_power
  (positive = discharging, negative = charging), battery_soc (kWh inside the dispatch window), and for pv_only
  battery_charge_from_grid.

### 4.5 Value, investment and choice (`engine/sizing.py`, `blocks/`)

- bill saving = baseline total cost - total cost with the battery (energy, export revenue, EaaS fee, capacity charges)
- yearly value = bill saving + ancillary revenue - EMS costs (fixed cost + fees on ancillary revenue + fees on the bill
  saving when positive; fees are 0% today)
- investment = battery price after subsidy + EMS hardware (bought once, not subsidised, not replaced)
- payback = investment / yearly value (infinite when the value is 0 or negative)
- lifetime profit = yearly value x battery life (10 yr) - investment
- choice: `profit` = highest lifetime profit among sizes whose payback <= battery life, else the shortest payback;
  `payback` = shortest payback; `custom` = tested size closest to `custom_kwh`
- default sizes 100 to 1,500 kWh by 100; with a threshold subsidy (CH, OCAN: max size = yearly load / 365 x 0.6) the
  list stops at the subsidised maximum, which is always tested; optional `fine_grid_kwh` sizes within
  `fine_window_kwh` of the best are tried after
- CH regime check: when a size's DUP lands in the other regime, it is solved twice more (DUP locked in the starting
  regime; other regime with DUP locked there) and the better one is kept
- replacements over the PV life: 1 full purchase + (25/10 - 1) x 60% of the gross price, unsubsidised

### 4.6 Ancillary services

Always applied, from `params/ancillary/<country>.json`: 25% of the SoC window and the same share of the power are
kept out of the dispatch; revenue = reserved kW x rate (CH 90 CHF/kW/yr; NL, FR 98.1 EUR/kW/yr). There is no switch
in the model. To leave them out of a study, set in the case file:
`"overrides": {"ancillary": {"rate_per_kw_year": 0, "reserve": {"mode": "percent", "frac": 0}}}`.
Effect on the examples: FR picks 200 kWh at 1,825 EUR/yr with ancillary, 100 kWh at -1,038 EUR/yr without.

### 4.7 Outputs

`summary_<tag>.json`: regime with and without battery, chosen size, investment, yearly value and its split, EMS
costs and fees, payback, lifetime profit, cycles, SC/SS with and without battery, Voltiris saving, bills, import and
export MWh, and the sweep. `results_<tag>.xlsx` sheets: Summary, Sizing sweep, Payback, Yearly bills, Monthly no
battery, Monthly battery, Dispatch.

## 5. Conventions and gotchas

- Results are deterministic: the same case gives the same numbers to the last digit. Any refactor can be checked by
  comparing the summary and every table exactly, before and after.
- Do not add a tie-break to the objective (see 4.4). Do not switch the HiGHS algorithm: interior point, primal and
  parallel simplex were tested and were 1 to 17 times slower than the default dual simplex.
- PyPSA writes simple bounds as constraints: a CH solve with a battery has about 245,000 variables and 543,000
  constraints, 420,000 of them bounds. HiGHS presolve removes them, but building them costs about 3 s per solve.
- The FR supplier file sets `battery_export: "pv_only"`; a site allowed to trade sets
  `"overrides": {"tariff": {"battery_export": "any"}}`.
- Values marked UNCONFIRMED in parameter notes are still to be confirmed (for example the FR subsidies from the
  notebook, and the module Wp: the yield file says 145, the model uses 146).
- `elements/battery_reference/README.md` "For Paul" lists how the model differs from the Pre-feasibility site (tariff as
  parameters, finance in the model, result shape). Jesse's decision (22 Oct): the site adapts to the model.

## 6. The browser interface (`interface/`)

Added 28 Oct 2026 as `models/battery_interface/`; moved the same day to `interface/` and made independent of the
battery model (details in `interface/README.md`). It only imports `elements/battery_reference` and changes nothing in it.

- `app.py` starts a local server (Python standard library, 127.0.0.1 only, port 8775 or the next free one) and
  opens the browser. `server.py` serves `web/` and a small JSON API; `api.py` is generic (blocks, presets, each
  block's input file and time step, run state); `adapters/battery_study.py` is the only file that calls this model:
  `run_case.load_case`, `setup_from_case`, `pipeline.run`, `write_results`, plus read-only previews
  (`parameters.load`, `inputs.from_frame`, `Setup`, `dispatch.grid_limits_kw`, `dispatch.exclusive_steps`,
  `pipeline.choose_regime`). `adapters/system_study.py` runs the blocks.
- Pages: System (a clickable drawing of the greenhouse and its blocks, presets, the model when two fit, data year),
  one page per chosen block (its own input file, curves by year, month or week, its technical settings), Input data
  (every curve together), General (Market, Commercial, Subsidies, EMS), Run (setup check, case file, live log and
  progress, JSON overrides), Results (why this size, value split, sweep, with and without battery, bills by component,
  the whole year per day, dispatch per week, monthly tables, payback, downloads).
- The ancillary switch is on by default; off writes the overrides of 4.6 into the case file, and a case with those
  overrides reopens with the switch off.
- The page writes system cases (one input file per block). For this model a run writes the blocks' inputs as one
  workbook `input_<tag>.xlsx` and the case in its format `case_<tag>_reference.json`, then runs those. Each run
  writes `case_<tag>.json`, `summary_<tag>.json`, `results_<tag>.xlsx` to `interface/app_runs/<tag>/`; uploads go
  to `interface/app_data/uploads/`.
  On the CH, NL and FR examples the summary and every result sheet are identical to the old interface's (checked
  28 Oct 2026).
- Charts use Chart.js 4.4.1 stored in `web/chart.umd.js`, so the page works offline.

## 7. Run time

Measured 28 Oct 2026 in a 2-core sandbox, examples workbook:

- 98% of a study's time is the LP solves; reading the workbook takes about 1.4 s, writing the Excel file about 4 s.
- CH: 7 to 15 s per size; a default study (16 sizes up to the OCAN cap of 2,495 kWh) takes about 150 s.
- FR is the slow market: 11 s per size at 100 to 300 kWh, 50 s at 500, about 160 s at 1,000 to 1,500 kWh, so a
  default FR study takes roughly 20 to 25 min.
- Jesse's laptop figures in `elements/battery_reference/README.md` (35 to 80 s per size) predate the changes below.

**Changes made on 28 Oct** (in `engine/sizing.py` and `engine/pipeline.py`; results identical to the last digit on
the CH, FR and NL examples; 35 tests pass):

1. Memory is freed after each size (`gc.collect()`): a solved PyPSA network holds reference cycles, and memory grew
   by about 0.5 GB per size (3 GB after 5 sizes; a 16-size run ran out of memory in the sandbox). Now flat, peak
   about 1.2 GB.
2. The chosen size is not solved a second time: `sizing.sweep(..., dispatches=dict)` keeps every solved size's
   dispatch table under `(size, regime, dup_lock or "")`, and the pipeline reuses it (it solves again only if the key
   is missing).

Example studies went from about 41 to 24 s (CH), 48 to 23 s (FR) and 41 to 25 s (NL).

**Not done yet, in order of value:**

- Solve sizes in parallel (each HiGHS solve uses one core; the user's laptop has a 16-core Core Ultra 7 265H). Two
  workers gave 1.4x on 2 cores with identical results; 6 to 8 workers should give roughly 4x. About 1 GB per worker.
- Fewer sizes: a coarse list plus the existing fine grid, or stop the sweep when lifetime profit has dropped twice in a
  row. Risk: a curve with two peaks (CH regime switch, subsidy cap).
- Warm start between sizes (change the battery bounds in the HiGHS model and re-run): 2.5x faster on CH with the same
  optimum, but slower on FR, where the one-meter coefficients also change.
- A lean LP without the PyPSA layer: saves about 3 s per solve; a rewrite that needs full re-checking.

## 8. History of the work with Claude (23 to 28 Oct 2026)

- **Cleanup**: kept only the battery model. Removed the other Pre-feasibility models and their launcher:
  `models/clean` (consumption cleaner), `models/deck` (deck builder), `models/size` (solar-only sizing),
  `src/lib` (its TypeScript), `models/host.py`, `models/run.py`, `models/engines.json`, `models/releases.json`. They
  are still in `Voltiris/prefeasibility`. Root README rewritten for a battery-only folder.
- **Examples**: `examples/battery/` holds a synthetic workbook (2026, 15 min) and case files for CH, FR and NL
  (sweep 100 and 200 kWh to keep them quick; with the CH OCAN cap the CH case also tests 2,495 kWh).
- **Documentation** (published as Claude artifacts, not in this folder): model logic and diagrams for CH, FR and NL;
  lists of inputs, outputs and hard-coded values per market; a comparison table of the three markets; a checklist of
  every feature of the model; architecture diagrams.
- **battery_v2**: a rewrite with one module per idea and an ancillary on/off switch. It matched this model within
  1e-6 on 9 cases in both switch positions. Deleted on 28 Oct at the user's request; this model stays the reference.
- **Browser interface** for this model: section 6.
- **Run time**: analysis and the two changes of section 7.
- **Architecture page** of this model (private Claude artifact): https://claude.ai/artifact/AtNqPbUpVHB89F6aWw3sHN

## 9. Working on it

- Change numbers in `params/`, not in code. A new utility is a new
  `params/tariffs/<country>/<region>/<utility>_<year>.json`; a new canton adds `_canton.json` and
  `params/subsidies/CH/<canton>.json`; a new country adds `_country.json`, `subsidies/<country>/` and
  `ancillary/<country>.json`.
- New blocks: put rules that use parameters in `blocks/`, wire them into `engine/setup.py` (built once per study) and
  use them from the engine; add tests in `tests/test_battery.py`.
- Before and after any change to the engine, run the three example cases and compare the summaries and tables
  exactly, and run the tests.
