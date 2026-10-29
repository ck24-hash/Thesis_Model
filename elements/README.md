# elements: one folder per block

| Folder | Block | Status |
|---|---|---|
| `greenhouse/` | greenhouse demand | electricity load; heat and CO2 demand with a heat block |
| `voltiris/` | Voltiris PV | runs |
| `existing_pv/` | PV already on site | runs |
| `grid/` | import, export, tariffs, markets | runs: CH SIG, NL Westland Infra, FR TURPE 7 HTA |
| `battery/` | battery, its sizing and payback study | runs |
| `gas_supply/` | natural gas from the network: price, emission factor, carbon levy | runs |
| `ng_boiler/` | natural gas boiler, its sizing study | runs (values TO CHECK) |
| `thermal_storage/` | heat storage (hot water tank), three heat loss models, its sizing study | runs (values TO CHECK) |
| `battery_reference/` | Jesse's PV + battery model, frozen | the reference the blocks are checked against |

A block holds the technical side of one part of the system. What applies across blocks (business model, prices,
lifetimes, subsidies, EMS) is in `general/` (its README). The engine that puts both together is in `system/`. Run a case with `python system/run_case.py case.json`;
compare with the reference with `python system/compare.py case.json`. What each block needs as input, with an example
file for each: `examples/blocks/README.md`.

## What a block is

`<block>/block.py` gives:

| Name | What it is |
|---|---|
| `ID` | the block's name, as in `common/blocks.json` and the case file's `blocks` |
| `CARRIERS` | what it takes and gives (electricity, heat, CO2 and gas are modelled) |
| `COLUMNS` | the columns of its own input file: role, default name, unit, kind (power, energy, price, state) |
| `OWNS` | the parameter groups and keys it owns; a run's overrides go to the block that owns them |
| `load_params(market, ...)` | its parameters from its own `params/`, money in the market's currency (`common/parameters.py`) |
| a class | built from its parameters and columns; `add_to(network, ...)` adds its PyPSA components to its buses (`main` for electricity, `heat`, `co2`, `gas`) |

Rules:

- Each block reads its own input file (`blocks.<id>.input_file` in the case); `system/setup.py` reads them, brings a
  coarser step to 15 min and aligns them on the greenhouse load's time steps.
- A block adds only its own components and reads only its own parameters and columns.
- A rule that joins two blocks is in `system/dispatch.py`, not in a block: the site's PV (Voltiris + existing PV,
  one must-run generator behind the one meter, as in the reference), the one-meter rule, PV-only battery export,
  EaaS on the grid.
- Component names are the reference model's (`pv`, `load`, `grid_import`, `grid_export`, `battery_store`,
  `bat_charger`, `bat_discharger`), and the engine adds them in the reference model's order, so the LP is the same.
- Parameter files keep the reference model's layout (`tech`, `capex`, `finance`, `subsidies`, ...), split by owner.
  A value not from a source is written with "TO CHECK" in its note (the gas boiler's, the heat storage's and the
  carbon levy's values).
- The heat side (buses `heat`, `co2`, `gas`) is added only when the system has a heat block, so a system without one
  gives the same LP as the reference.
