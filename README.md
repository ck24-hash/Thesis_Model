# Greenhouse energy model

Master thesis model (EPFL, with Voltiris): how a commercial greenhouse can supply more of its own heat, CO2 and
electricity. The thesis logic is in `thesis.md`, the plan for building the blocks in `PLAN.md`.

Today the electricity side runs: greenhouse load, Voltiris, existing PV, grid and battery, each a block in
`elements/`, put together by `system/`. They give the same results as Jesse's PV + battery model
(`elements/battery_reference`), which stays frozen as the reference. On the heat side, the greenhouse's heat and CO2
demand, the gas supply, the gas boiler, the heat pump (outside air, COP from the outside temperature), the heat
storage and bought CO2 run; the CHP, SOFC, data center and electric backup heater are planned. The sized blocks are
always sized together, for the site's lowest yearly cost, and at each step the heat comes from the cheapest source.
Every run reports, technical results first: each size and how it was found, the year's energy, the site's yearly
cost, the electricity side (supply and demand, self-consumption, the grid bill), each technology with and without
it, how much each size matters (-10 % and +10 %) and, when the model sizes the battery, a check against the
reference model's battery sweep.

## Contents

```
interface/               one browser interface for every run: choose a scenario or build your own system
system/                  the engine: builds one network from the chosen blocks and solves it; the joint sizing, the
                         studies, the electricity side, the yearly cost, each technology with and without it, the
                         technical summary, the sensitivity, the battery check
elements/                one folder per physical block, its technical side (elements/README.md)
  greenhouse/            electricity load, heat and CO2 demand
  voltiris/              Voltiris PV output
  existing_pv/           PV already on site
  grid/                  markets, tariffs, import and export, capacity charges
  battery/               battery, its payback study and size sweep (the battery check)
  gas_supply/            natural gas: price, emission factor, carbon levy
  ng_boiler/             gas boiler, its year at its size
  heat_pump/             heat pump on the outside air: COP constant or from the outside temperature, sized together
  thermal_storage/       heat storage: efficiencies, three heat loss models, its year in the system
  external_co2/          bought CO2: buy it or burn gas for it, whichever costs less
  battery_reference/     Jesse's PV + battery model, frozen
general/                 what is not a physical block (general/README.md)
  commercial/            business model, investment prices, lifetimes, ancillary revenue rate
  subsidies/             Voltiris and battery subsidies
  ems/                   energy management system costs
common/                  shared by every block and the interface
  timeseries.py          time step detection, coarser data (hourly, 30 min) to 15 min
  parameters.py          parameter files, money in the market's currency, overrides
  blocks.json            every technology of the thesis, whether it runs today, and the links between blocks
  scenarios.json         the scenario presets (thesis.md section 2.1)
examples/blocks/         one input file per block, case files for CH (also with existing PV and the heat blocks), FR, NL;
                         the list of what each block needs
examples/battery/        the reference model's example: one workbook, case files for CH, FR and NL
```

Each block reads its own input file; hourly files are converted to 15 min. What each block needs, with an example of
each: `examples/blocks/README.md`.

## Install

Python 3.12 or later and one virtual environment:

```
pip install -r elements/battery_reference/requirements.txt
```

## Run

From this folder:

- browser: `python interface/app.py` (opens http://127.0.0.1:8775)
- command line, the blocks: `python system/run_case.py examples/blocks/case_blocks_CH.json`
- command line, the reference model: `python elements/battery_reference/run_case.py case.json`
- the blocks' battery sweep and the reference model on the same case files, compared:
  `python system/compare.py case.json [more]`
- hourly workbook to 15 min, without the interface:
  `python common/timeseries.py input.xlsx --year 2026 --kind "Loadcurve (kW)=power" --kind "Day ahead kWh=price"`

The command lines write `summary_<tag>.json` and `results_<tag>.xlsx` next to the case file (or to its
`output_dir`), so running an example case writes them into `examples/blocks/` or `examples/battery/`. The interface
writes to `interface/app_runs/<tag>/`; `compare.py` writes nothing.

Tests: `python -m pytest system/tests common/tests elements/battery_reference/tests -q` (about 4 min).

Ancillary services are always applied (the reserve in `elements/battery/params/ancillary/<country>.json`, the rate in
`general/commercial/params/ancillary/<country>.json`). To leave them out of a
run, add the overrides `{"ancillary": {"rate_per_kw_year": 0, "reserve": {"mode": "percent", "frac": 0}}}` to its
case file, or turn the switch off in the interface's battery card.

## Documentation

- `thesis.md`: the thesis scope, scenarios, blocks, assumptions register.
- `MODEL_OVERVIEW.md`: every block with its parameters, and the optimisation in plain terms, for a presentation.
- `FORMULATION.md`: the whole model as a mathematical optimisation problem: notation, objective, constraints, sizing
  and results, formulas only.
- `OPTIMISATION.md`: how the model optimises: the yearly dispatch, the joint sizing, the site's yearly cost, each
  technology with and without it, the sensitivity and the battery check, with the formulas and the reasoning.
- `PLAN.md`: how the blocks are built and connected, and in which order.
- `elements/README.md` and each block's README: what a block is, its equations and parameters.
- `general/README.md`: the general items (commercial, subsidies, EMS).
- `system/README.md`: the engine, the case format, the sizing, the check against the reference.
- `context.md`: the reference model's history and conventions, and the state of the work.
- `elements/battery_reference/README.md`: every reference model parameter and how it works.
- `interface/README.md`: the interface and its run types.
- `examples/blocks/README.md`: the blocks, their inputs and the example files.
- `examples/battery/README.md`: the reference model's example files.
