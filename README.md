# Greenhouse self-sufficiency model (PyPSA)

Master thesis, EPFL x Voltiris: *A Path to Greenhouse Self-Sufficiency: Heat and CO2*.
Hourly dispatch model of a commercial greenhouse (one year, linear program, HiGHS solver).

| Scenario | Notebook | Status |
|---|---|---|
| Baseline: NG boiler + thermal storage + grid import | `notebooks/01_baseline.ipynb` | implemented |
| S1: gas CHP + backup boiler + thermal storage + grid import/export | `notebooks/02_s1_chp.ipynb` | implemented |
| S2–S4 (Voltiris, heat pump, battery, data center, SOFC) | – | to do |

Documentation: `docs/blocks/` (one page per model block), `docs/repository/` (repository structure),
`docs/scenario_report.pdf` (3-page summary of the implemented scenarios).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
pytest                             # about 2 min, should pass
```

Open the folder in VS Code, open a notebook, pick the `.venv` interpreter as kernel and run all cells.
If the input file does not exist, a **synthetic dummy dataset** is created so the notebook runs (the numbers mean nothing).

## Your own data

Put an Excel file at `data/baseline_input_data.xlsx` (Baseline) or `data/s1_input_data.xlsx` (S1), sheet `hourly`,
one row per hour (8760 or 8784) or per day (365 or 366), columns:

| Column | Unit |
|---|---|
| `timestamp` | hourly datetime, no DST gaps or duplicates |
| `heat_demand_kW` | kW thermal |
| `elec_demand_kW` | kW electric |
| `co2_demand_kg_h` | kg CO2 per hour |
| `gas_price_EUR_per_MWh` | EUR per MWh fuel, LHV, all-in |
| `elec_price_EUR_per_MWh` | EUR per MWh, all-in import price |
| `grid_emission_factor_kg_per_kWh` | optional, hourly grid emission factor |
| `elec_export_price_EUR_per_MWh` | EUR per MWh paid for exported electricity; **required for S1**, ignored by the Baseline |

Example files: `data/baseline_input_data_EXAMPLE_dummy.xlsx`, `data/s1_input_data_EXAMPLE_dummy.xlsx` (with the export price).

Other headers or units: edit `INPUT_COLUMNS` in `src/ghmodel/config.py` (header and conversion factor to MW, t/h, EUR/MWh).

**Resolution is decided by the number of rows**: 365 or 366 rows = daily, 8760 or 8784 rows = hourly (366 and 8784 =
leap year). If there is a `timestamp` column it must match (strict steps of 1 day or 1 hour), and a warning is given if the
data do not cover exactly one calendar year (for example 366 rows starting in 2023). Without a timestamp column the
index starts at `START_TIMESTAMP` in the notebook, so for a leap year set it to a leap year (e.g. 2024).
Other row counts are read as hourly or daily from the timestamps, with a "not a full year" warning.

**Daily data** is converted to hourly. Keep the same
column headers, but the demand columns (`heat_demand_kW`, `elec_demand_kW`, `co2_demand_kg_h`) must hold **daily totals**
(kWh/day, kg/day): each is divided by 24 and spread evenly over the day. Prices and the grid emission factor are copied to
every hour of the day. Which columns are split is set by `DAILY_TOTAL_COLUMNS` in `config.py`.
`data/*.xlsx` is git-ignored (real data may be confidential), only the `*EXAMPLE*` file is tracked.

## Structure

```
src/ghmodel/
  config.py          Params (all parameters + defaults) and Excel column mapping
  data.py            read/check the Excel (hourly or daily), dummy data generator
  sizing.py          None -> automatic sizes, annualised cost factors
  blocks.py          reusable blocks: buses, loads, gas supply, grid import/export, boiler, CHP, CHP priority,
                     thermal storage, custom constraints, sinks, slack
  scenarios/
    baseline.py      composes the blocks into the Baseline network
    s1_chp.py        composes the blocks into the Scenario 1 network
  workflow.py        solve(), run_scenario()
  results.py         hourly results, balance checks, KPIs (same layout for all scenarios), Excel export
  analysis.py        storage value, financial analysis (payback, NPV, IRR), scenario comparison
  plots.py           all figures
notebooks/           thin notebooks: set parameters, run, plot (01_baseline, 02_s1_chp)
tests/               pytest checks
scripts/             stand-alone helpers (kew_extract_demand.py: daily demand from KasEnergieWijzer)
data/   results/     inputs / outputs
docs/                scenario figure, block documentation, repository structure, report
```

Rule of thumb: **logic goes in `src/ghmodel`, notebooks only call it.** This keeps scenarios comparable and git diffs
readable. Details: `docs/repository/README.md`.

## Size optimisation

`Params.OPTIMISE_BOILER`, `OPTIMISE_TES` and `OPTIMISE_CHP` (default `False`): the size is a fixed input. If `True` the size becomes a
decision variable and annualised capex (capex, lifetime, discount rate, fixed O&M) enters the objective.
`tes_capacity_max_MWh` optionally limits the storage size. When `OPTIMISE_TES = True`, storage charge/discharge power is limited to capacity / `tes_hours_at_full_power` (custom constraint in `blocks.add_custom_constraints`; `None` = no limit).

## Financial analysis

`analysis.financial_analysis(res, res_ref, P)` compares the equipment of a scenario (the greenhouse is excluded) with a
reference run on the same data: S1 against the Baseline; in the Baseline, the storage against the Baseline without
storage (the boiler has no alternative there, so its own payback is not defined). Cash flows over
`project_lifetime_y` (20 y): additional investment in year 0, yearly operating saving (incl. export revenue) minus
additional fixed O&M, replacements at the end of each lifetime, straight-line salvage value at the horizon.
Outputs: simple and discounted payback, NPV at `discount_rate`, IRR (only if the investment pays back), saving on the
total annualised cost, CO2 change and abatement cost, investment per m², and a first-order NPV sensitivity (±20 % on
prices and investment, dispatch not re-optimised).

## Adding a scenario (S2 to S4)

1. Add the new blocks to `blocks.py` (for example `add_heat_pump`, `add_battery`, `add_voltiris`, `add_data_center`, `add_sofc`)
   and one page per block in `docs/blocks/`. Keep the bus names and the link port convention described at the top of that file.
2. Create `scenarios/<name>.py` with a `build(data, P, sizes)` function that composes the blocks (see `s1_chp.py`).
3. Add the new components to `results.extract_results` / `summarise` (zero if absent, so the KPI table keeps the same rows)
   and to `analysis.investments`.
4. Add the new inputs (for example Voltiris profile, COP) to `config.py` / `data.py`.
5. Add a test file in `tests/` and a notebook (copy the structure of `02_s1_chp.ipynb`).
6. Run: `n, res = run_scenario(<name>.build, data, P)`.

## Main assumptions (Baseline and S1)

Energy system
- Boiler is the whole heating system, sized 1.2 x peak heat demand, so no separate backup is drawn.
- CO2 only comes from the boiler flue gas (`boiler_co2_usable_fraction` = 1.0, placeholder).
- Surplus heat can be dumped and surplus CO2 vented, unlimited and free by default (**not drawn in the scenario figure**). A cost can be set later with `heat_dump_cost_EUR_per_MWh` / `co2_vent_cost_EUR_per_t`.
- Stored heat returns to the same heat bus, so it could in principle also be dumped (not drawn; never optimal, accepted simplification).
- Gas supply is unlimited (no connection capacity limit, not drawn). Grid import limit is 10 x peak electricity demand (not binding).
- No minimum load (pure LP). Boiler output may change by at most 50 % of its capacity per hour (`boiler_ramp_limit_per_h`, placeholder; `None` = off).
- One-node thermal storage at one temperature, same level at start and end of the year.
- Storage charge and discharge power are at most capacity / 4 h (`tes_hours_at_full_power`, placeholder; `None` = off). With fixed sizes the power is the smaller of this and the boiler capacity; with `OPTIMISE_TES` it is a linear constraint on the optimised sizes.
- Storage keeps a reserve of 10 % of its capacity that is never used (`tes_min_soc_frac`, placeholder; 0 = off). The reserve still has standing losses, which the boiler must make up.

Scenario 1 (CHP)
- Gas-engine CHP with fixed ratios (back-pressure): η_el 0.42, η_th 0.45 (LHV, placeholders), all exhaust CO2 usable
  (placeholder; real engines need flue-gas cleaning). No minimum load, no start-up cost (pure LP).
- CHP size: 50 % of peak heat demand as thermal capacity (placeholder), converted to MW_el. Backup boiler sized as in the
  Baseline (1.2 × peak heat, full backup). Storage as in the Baseline.
- **CHP priority**: the CHP is dispatched before the backup boiler and grid import, via an internal penalty
  (200 EUR/MWh on boiler heat and grid import). The penalty steers the dispatch only and is excluded from all reported
  costs. `chp_priority = False` gives cost-optimal dispatch.
- Exported electricity earns the hourly export price (input column) and is counted as revenue; no export limit by default.
  Simultaneous import and export is not forbidden (never profitable while export price < import price).
- Exported electricity does not reduce the reported emissions; the displaced grid CO2 is shown for information only.

Finance
- Investment = capex × size (overnight, no subsidies, no financing cost); replacements at the end of each lifetime and
  straight-line salvage value at the 20-year horizon; constant prices over the horizon (no escalation).

Prices and emissions
- Gas price is all-in per MWh LHV (confirmed), but **without** the carbon levy: the levy is added separately (`co2_price_EUR_per_t`, default from `country`).
- Electricity price is all-in.
- All CO2 from burning gas counts as emitted, including the part dosed into the greenhouse (no credit for crop uptake).
- Grid emissions use a constant factor per country (`grid_co2_factor_t_per_MWh`, default from `country`) unless an hourly column is given.
- Country defaults (`COUNTRY_DEFAULTS` in `config.py`, all placeholders): carbon levy CH 125, FR 44.6, NL 0 EUR/t; grid factor CH 0.10, FR 0.05, NL 0.30 t/MWh.

Data and solver
- Input must be strictly hourly or strictly daily; a warning is given if it is not a full year (8760 or 8784 h).
- Daily input: demand is spread evenly over the 24 hours (flat profile, no day/night pattern). This underestimates heat and
  CO2 peaks and the need for storage, and puts CO2 dosing at night. Hourly data should be used for final results.
- HiGHS with its default settings written out in `Params.solver_options`, 1 h time limit.
- Parameters marked `[placeholder]` in `config.py` are not sourced yet.

## Using Claude Code in this folder

`CLAUDE.md` gives Claude Code the thesis context, units and conventions, so you do not need to repeat them.
