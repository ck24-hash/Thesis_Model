# elements: one folder per block

| Folder | Block | Status |
|---|---|---|
| `greenhouse/` | greenhouse demand | electricity load only |
| `voltiris/` | Voltiris PV | runs |
| `existing_pv/` | PV already on site | runs |
| `grid/` | import, export, tariffs, markets | runs: CH SIG, NL Westland Infra, FR TURPE 7 HTA |
| `battery/` | battery, its sizing and payback study | runs |
| `battery_reference/` | Jesse's PV + battery model, frozen | the reference the blocks are checked against |

The engine that puts the blocks together is in `system/`. Run a case with `python system/run_case.py case.json`;
compare with the reference with `python system/compare.py case.json`.

## What a block is

`<block>/block.py` gives:

| Name | What it is |
|---|---|
| `ID` | the block's name, as in `common/blocks.json` and the case file's `blocks` |
| `CARRIERS` | what it takes and gives (today only electricity is modelled) |
| `COLUMNS` | the workbook columns it reads: role, default name, unit, kind (power, energy, price, state) |
| `OWNS` | the parameter groups and keys it owns; a run's overrides go to the block that owns them |
| `load_params(market, ...)` | its parameters from its own `params/`, money in the market's currency (`common/parameters.py`) |
| a class | built from its parameters and columns; `add_to(network, ...)` adds its PyPSA components to the bus `main` |

Rules:

- A block adds only its own components and reads only its own parameters and columns.
- A rule that joins two blocks (the one-meter rule, PV-only battery export, EaaS on the grid) is in
  `system/dispatch.py`, not in a block.
- Component names are the reference model's (`pv`, `load`, `grid_import`, `grid_export`, `battery_store`,
  `bat_charger`, `bat_discharger`), and the engine adds them in the reference model's order, so the LP is the same.
- Parameter files keep the reference model's layout (`tech`, `capex`, `finance`, `subsidies`, ...), split by owner.
  A value not from a source is written with "TO CHECK" in its note (none yet: every value comes from the reference).
