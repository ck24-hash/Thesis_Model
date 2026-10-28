# Battery model: example input files (synthetic data)

Made up for trying the model. The numbers mean nothing: no real site or grower is behind them.

- `Example_input_PV_synthetic_2026.xlsx`: the input workbook. One row per 15 minutes of 2026 (35,040 rows), columns:
  `Month`, `Day`, `Hour`, `Minute`, `Loadcurve (kW)`, `Production voltiron (W)` (per module), `Current PV feed-in (kW)`
  (all 0, used only if `use_existing_pv` is true), `Day ahead kWh` (EUR/kWh; NL and FR need it).
- `case_example_CH.json`, `case_example_NL.json`, `case_example_FR.json`: the case file for each market
  (500 modules, direct sales, battery sizes 100 and 200 kWh). They differ only in `market` and `tag`.

## Run (from the project folder)

    python system\run_case.py "examples\battery\case_example_CH.json"                     (the blocks)
    python elements\battery_reference\run_case.py "examples\battery\case_example_CH.json"   (the reference model)
    python system\compare.py "examples\battery\case_example_CH.json"                      (both, compared)

or open the case in the interface (`python interface\app.py`, step 1).

The results are written next to the case file: `summary_<tag>.json` and `results_<tag>.xlsx`.
Run time on a laptop: about 1 to 2 minutes per example (CH also adds the subsidised maximum size, so it picks
about 2,495 kWh there).

## Use for a real study

Copy the workbook format and one case file to a study folder outside this repo, replace the data and set
`input_file`, `pv_modules`, `grid` and `market`. Every key is described in `elements\battery_reference\README.md` and
at the top of `elements\battery_reference\run_case.py`; `elements\battery_reference\case_template.json` is the blank
case file. The blocks read the same case file (`system\setup.py` describes their own format).

Checked on 26 Oct 2026 (Python 3.13): all three cases run and write both result files.

## How to read the results

Each run writes `summary_<tag>.json` and `results_<tag>.xlsx`. They answer: for this site, which battery size should be
installed, and does it pay back? Money is in the market's currency (CHF for CH, EUR for NL and FR). The figures below are
from the CH example and mean nothing, because the data is synthetic.

### summary_<tag>.json (same as the Summary sheet)

| Group | Fields (CH example) |
|---|---|
| The choice | `battery_kwh` 2,495; `regime_battery` B (the tariff regime the site falls into) |
| Cost | `battery_net_capex` 249,500 (after the 75% subsidy); `ems_capex` 917; `battery_investment` 250,417 (the sum); `voltiris_capex_grower` 131,400 (the PV modules) |
| Yearly value of the battery | `battery_value_yr` 69,395 = arbitrage 23,109 + peak shaving 20,717 + ancillary 28,069 - EMS cost 2,500 |
| Return | `battery_payback_yr` 3.6 years; `battery_lifetime_profit` 443,534 |
| Energy | `ss_*` self-sufficiency (share of the load covered by PV, 5.4%); `sc_*` self-consumption (share of PV used on site, 100%); `import_mwh_*` and `export_mwh_*`, with and without the battery; `battery_cycles` per year |
| Bills | `bill_existing_pv_only` 289,289 (no PV in this example); `bill_no_battery` 273,728 (with the Voltiris PV); `bill_battery` 229,901 (PV and battery) |

`voltiris_saving_yr` is the yearly saving from the PV modules alone.

### results_<tag>.xlsx, sheet by sheet

| Sheet | What it holds |
|---|---|
| Summary | The same list as the JSON. |
| Sizing sweep | One row per battery size tried: yearly value, investment, payback, lifetime profit, self-sufficiency, self-consumption, regime. The chosen size is the best row by the objective in the case file (profit, payback or custom size). CH also adds the largest subsidised size to the list. |
| Payback | Whole-project scenarios: PV only (8.4 years); PV and battery with no subsidy (23.9 years); PV and battery with the CH battery subsidy (15.1 years). These are longer than the battery-only 3.6 years because they include the PV and the battery's replacements over 25 years. |
| Yearly bills | The bill split into import energy, network, federal levy, capacity charge (peak-demand fee), export revenue and total, in three columns: no PV, PV only, PV and battery. Also the kWh imported and the peak kW (252, 247, 99: the peak shaving). |
| Monthly no battery, Monthly battery | 12 rows each: import and export (MWh), costs, PV used directly or through the battery, self-consumption, self-sufficiency, billed peak, capacity charge. The battery sheet adds MWh charged and discharged. |
| Dispatch | Every quarter-hour of the year: load, PV, grid import and export, battery power and battery charge level (kWh). This is what the optimiser decided to do. Battery power is positive when discharging and negative when charging (engine/dispatch.py, results); battery charge level counts kWh inside the dispatch window only (0 to 0.6 x the size). |

Start with Sizing sweep (is the chosen size at an edge of the list or a clear optimum?), then Payback and Yearly bills to see
what the choice means for the project.
