# Plan: the blocks and how they work together

Written 28 Oct 2026, updated the same day after step 1, on 29 Oct 2026 (step 2 in part) and on 1 Nov 2026 (heat
pump, external CO2, each technology with and without it). The thesis logic is in `thesis.md`; this file says how the
code gets there.

## 1. Where we are

- `elements/`: the blocks greenhouse (electricity load, heat and CO2 demand), Voltiris, existing PV, grid, battery,
  gas supply, gas boiler, heat pump (outside air), heat storage and external CO2, their technical side. Planned, not
  built: CHP, SOFC, data center, electric backup heater.
  Each reads its own input file (`examples/blocks/README.md` lists what each needs, with an example).
- `general/`: what is not a physical block: commercial (business model, prices, lifetimes, ancillary rate),
  subsidies, EMS (`general/README.md`). The market is chosen once for the run.
- `system/`: the engine that builds one network from the chosen blocks, sizes the gas boiler, heat pump, heat storage
  and battery together, and reports for every system, technical first: each size and the year's energy, the
  electricity side, each technology with and without it; then the site's yearly cost; then each size -10 % and +10 %
  (operation only) and the battery check against the reference sweep.
- `elements/battery_reference`: Jesse's PV + battery model, frozen. The blocks give the same results to the last digit
  (section 5).
- `interface/`: five sections in tabs along the top (System, Input data, General, Run, Results); under System, one
  page per chosen block. For the electricity blocks both the blocks and the reference can run the system, and the page
  lets you choose.
- `common/`: time step conversion to 15 min, parameter loading and money, the list of blocks, the scenario presets.

## 2. Layout

```
elements/
  battery_reference/   Jesse's model, unchanged
  greenhouse/          one folder per block (section 3)
  voltiris/
  existing_pv/
  grid/
  battery/
  ...                  ng_boiler, thermal_storage, chp, heat_pump, data_center, sofc, external_co2, aux_heater
system/                the engine: builds one network from the chosen blocks, solves it and sizes the blocks; the
                       site's yearly cost, each technology with and without it; later the other KPIs
common/                shared: timeseries, parameters, money, network helpers, blocks.json, scenarios.json
interface/adapters/    one run type per model: blocks (system_study.py), battery_study (the reference)
```

The folder is `elements/`, not `blocks/`: Jesse's model has its own internal package called `blocks` (and `engine`,
`parameters`, `run_case`), loaded by adding its folder to `sys.path`. With different names, his model and the blocks
load in one Python process (the interface and `system/compare.py` do this). New code is imported as packages from the
project root (`elements.voltiris.block`), never by adding a folder to `sys.path`.

## 3. What every block folder holds

```
elements/<block>/
  README.md        role, equations, parameters with their source, assumptions (IDs from thesis.md section 5)
  block.py         the block (below)
  params/          its parameter files; a value without a source is written with "TO CHECK" in its note
  sizing.py        optional: its size sweep (the battery, the gas boiler, the heat storage)
  study.py         optional: the block on its own, sized with the rest fixed (the battery, the gas boiler, the heat
                   storage); the heat pump's gives its results at the size of the joint sizing
  tests/           on invented numbers (today the checks are in system/tests)
```

`block.py` gives, built today (`elements/README.md`):

| Part | What it is |
|---|---|
| `ID`, `CARRIERS` | the block's name; the buses it takes from and gives to (electricity, heat, CO2 and gas are modelled) |
| `COLUMNS` | the input columns it needs, each with unit and kind (power, energy, price, state) for `common/timeseries.py` |
| `OWNS` | the parameter groups and keys it owns: a run's overrides go to their owner |
| `load_params(market, ...)` | its parameters from its own `params/`, money in the market's currency |
| a class with `add_to(network, ...)` | adds its PyPSA components on the shared bus |

Built with the heat and CO2 blocks, so the engine can report any system, not only the battery study: the flows per
step of every block, positive numbers (`system/dispatch.py` `results` and `heat_results`; the battery, heat pump and
heat storage give theirs with `results(network)`), and the site's yearly cost (`system/costs.py`: investment, O&M,
fuel, revenue, with the prices and lifetimes in `general/commercial`).

How blocks interact:

- Blocks meet only on buses. A block never reads another block's variables.
- A rule that needs two blocks is a system rule in `system/dispatch.py`, written once, naming the blocks it uses:
  today the one-meter rule (grid + battery, with the heat pump's draw in its import limit), the PV-only battery export
  (grid contract + battery) and EaaS on the grid (Voltiris business model + grid, decided 28 Oct 2026).
- Which block needs which is data in `common/blocks.json` (`fixed`, `needs`, `needs_one_of`, `follows`), checked by
  `system/setup.py`.
- Each bus balances at every step; `system/tests` checks the electricity, heat and CO2 buses and the heat storage.
- One currency per run, the market's.

## 4. The engine (`system/`)

Built: the case (`setup.py`: system format, or a reference case file read as the same system), the network and its
solve (`dispatch.py`), the bills, self-consumption and monthly tables (`flows.py`), the electricity side of every run
(`electricity.py`), the joint sizing (`joint.py`), the site's yearly cost (`costs.py`), each technology with and
without it (`effects.py`), the command line (`run_case.py`) and the comparison with the reference (`compare.py`).

To build with the next blocks:

1. Buses for heat and CO2 (and gas, ethanol, low-temperature heat) when a chosen block uses them. Done for heat,
   CO2 and gas (29 Oct 2026).
2. A plain run of a system (no sizing): flows of every block, balance check, KPIs (self-sufficiency in heat, CO2 and
   electricity, self-consumption; thesis.md section 10), money and emissions. In part: every run reports the
   electricity side (self-consumption, self-sufficiency), the site's yearly cost and the CO2 of the gas burnt; heat
   self-sufficiency and the grid's emissions are not computed yet.
3. Comparison against a reference run: the same system without the block being sized (block study), or another
   scenario (Baseline for S1 to S4, thesis.md section 11). The first is done for every technology (`system/effects.py`,
   1 Nov 2026); the comparison of scenarios is still to decide.

Sizing: a block study sweeps one block's size with the rest fixed. Since 29 Oct 2026 the sized blocks are sized
together by default (`system/joint.py`: one optimisation for the site's lowest yearly cost; always with a heat pump,
which has no size sweep), and the site's yearly cost is reported for every run (`system/costs.py`). Each technology's
value is the system without it optimised again (`system/effects.py`).

## 5. Step 1: the battery model split into blocks (done 28 Oct 2026)

| In elements/battery_reference | Now in |
|---|---|
| load column | `greenhouse` |
| module yield x module count, must run, module Wp | `voltiris` |
| business model, PV price, PV life, battery price tiers and replacements, battery life, ancillary rate | `general/commercial` |
| PV and battery subsidies | `general/subsidies` |
| EMS costs and fees | `general/ems` |
| existing PV column | `existing_pv` |
| tariffs, capacity charges, A/B regimes and DUP, export value, grid limits, markets | `grid` |
| battery technology, ancillary reserve, size sweep, payback study | `battery` |
| one-meter rule, PV-only battery export, EaaS import and export bounds | `system/dispatch.py` |
| parameter loading, money in the market's currency, exchange rate | `common/parameters.py`, `common/fx.json` |

Check (`python system/compare.py`): the summary and every result table equal to the last digit on the CH, NL and FR
examples (one workbook, and one file per block with an hourly existing PV file), and on variants (EaaS, existing PV,
0 modules, a custom size with a fine grid, overrides with ancillary off, a manual FR regime with
`battery_export: any`, FR under EaaS); results in `system/README.md`. Voltiris and existing PV are separate blocks
with separate files, added to the network as one PV generator, as in the reference.

Known problem for later steps: the one-meter rule and the PV-only export use the net load (load - PV) as a fixed
number per step. That holds while load and PV are fixed. Once a heat pump or a data center adds a variable electricity
load, the net load becomes a variable and these rules no longer hold as written. Options: (a) on/off switches (a MILP;
Jesse measured over 20 min per battery size), (b) a cost penalty on importing and exporting in the same step
(thesis.md section 3.9 allows it), (c) keep the rule only where the tariff makes cheating pay and check after the solve
that no step imports and exports at once. To decide in step 4 of section 6. With the heat pump (1 Nov 2026): where
exporting pays more than importing, the one-meter import limit is raised by the heat pump's draw; under EaaS the heat
pump runs on the PV surplus first and the site imports only what it draws beyond it (4 Nov 2026); the PV-only battery
account still uses the greenhouse load (thesis.md A23).

## 6. Build order

Each step ends with the tests passing, balances closed, the block README and assumptions written, and the interface
able to run it.

0. Interface out of the battery model (done 28 Oct 2026).
1. `system/` + greenhouse (electricity) + Voltiris + existing PV + grid + battery, reproducing the reference (done
   28 Oct 2026).
2. Greenhouse heat and CO2 demand, gas supply, gas boiler, thermal storage, and the plain system run of section 4:
   Baseline runs. Done 29 Oct 2026: heat and CO2 demand, gas supply, gas boiler and heat storage with their sizing
   studies (values TO CHECK), the electricity side of every run, the joint sizing and the site's yearly cost; 1 Nov
   2026: each technology with and without it (`system/effects.py`). To do: comparing scenarios (how, to decide), real
   data.
3. CHP: S1.
4. Heat pump, ambient source: S2, then S2 + battery. Decide the one-meter question (section 5). Done 1 Nov 2026: the
   heat pump on the outside air, COP constant or from the outside temperature, sized jointly or fixed (values TO
   CHECK); the one-meter question as in section 5.
5. External liquid CO2 and the electric backup heater (A1): S2 + battery + external CO2. External CO2 done 1 Nov 2026
   (values TO CHECK); the backup heater is still to build.
6. Data center and the heat pump on its waste heat: S3 and its variants.
7. SOFC on ethanol: S4.
8. Inputs for CH, FR and NL, scenario comparison tables, sensitivity runs (thesis.md sections 11 to 13).
9. Sizing all blocks together: done for the boiler, heat storage and battery (29 Oct 2026) and the heat pump (1 Nov
   2026); each new block joins it.

## 7. Decisions

Taken 28 Oct 2026:

1. Blocks live in `elements/` (first `blocks/`, renamed to avoid the clash of section 2); Jesse's model is
   `elements/battery_reference`.
2. Existing PV is a block of its own.
3. Voltiris declares its business model; the system applies EaaS to the grid.
4. Ancillary services sit in the battery block; the rate is in a file per country.

Still needed:

5. **Data** for step 2 onwards (thesis.md section 14): greenhouse heat and CO2 demand, or the crop and climate settings
   to build them.
