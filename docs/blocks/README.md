# Model blocks: overview

Each block is one function in [`src/ghmodel/blocks.py`](../../src/ghmodel/blocks.py) that adds one part of the system
to a PyPSA network. A scenario (for example [`scenarios/baseline.py`](../../src/ghmodel/scenarios/baseline.py)) is a list of
block calls. This folder documents every block that exists so far (Baseline and Scenario 1 of
[`docs/Scenarios.png`](../Scenarios.png)).

| # | Block | Function | Used in | Drawn in the figure? |
|---|---|---|---|---|
| 1 | [Buses and carriers](01_buses.md) | `add_buses` | Baseline, S1 | yes (the arrows' colours) |
| 2 | [Greenhouse demands](02_greenhouse_loads.md) | `add_greenhouse_loads` | Baseline, S1 | yes (Greenhouse box) |
| 3 | [Natural gas supply](03_gas_supply.md) | `add_gas_supply` | Baseline, S1 | yes (Fuel supply) |
| 4 | [Grid import](04_grid_import.md) | `add_grid_import` | Baseline, S1 | yes (Electricity grid) |
| 5 | [Natural gas boiler](05_ng_boiler.md) | `add_ng_boiler` | Baseline (main), S1 (backup) | yes (Conventional / Backup boiler) |
| 6 | [Thermal storage](06_thermal_storage.md) | `add_thermal_storage` | Baseline, S1 | yes (Thermal storage) |
| 7 | [Custom constraints](07_custom_constraints.md) | `add_custom_constraints` | all (automatic) | n/a (extra equations) |
| 8 | [Heat dump, CO2 vent and slack](08_sinks_and_slack.md) | `add_sinks_and_slack` | Baseline, S1 | **no: assumptions** |
| 9 | [Gas CHP](09_chp.md) | `add_chp` | S1 | yes (CHP) |
| 10 | [Grid export](10_grid_export.md) | `add_grid_export` | S1 | yes (CHP → grid) |
| 11 | [CHP priority](11_chp_priority.md) | `add_chp_priority` | S1 | n/a (merit order rule, dispatch weight only) |

Scenario compositions: [`scenarios/baseline.py`](../../src/ghmodel/scenarios/baseline.py) uses blocks 1–8,
[`scenarios/s1_chp.py`](../../src/ghmodel/scenarios/s1_chp.py) uses blocks 1–11.

## Common conventions

- **Units**: MW (power), MWh (energy), t/h and t (CO2), EUR. Prices in EUR/MWh and EUR/t. Gas is measured on an LHV basis.
- **Time**: one year, hourly snapshots (8760 or 8784), each with a weight of 1 h, so MW in one hour = MWh. Daily input is
  converted to hourly before the model is built (see README, "Your own data").
- **Bus balance**: at every bus and every hour, inflow = outflow. This is the main constraint that links all blocks.
- **Links** (converters): `p0` is the flow taken from `bus0` (positive). The flow delivered to `bus1`/`bus2` is
  `efficiency × p0` / `efficiency2 × p0`, and PyPSA reports it as negative `p1`/`p2`. Link capacity `p_nom` is on the
  `bus0` side, so a boiler with thermal capacity Q has `p_nom = Q / η`.
- **Sinks** are Generators with `sign = -1`: a positive value means energy leaves the bus.
- **Parameters** live in `Params` ([`config.py`](../../src/ghmodel/config.py)). `None` means "sized automatically" or "use
  the country default". Values marked `[placeholder]` are not sourced yet.
- **Results**: [`results.py`](../../src/ghmodel/results.py) builds the hourly table `r` in which every flow is positive, and
  the annual KPI table `summary`.

## The optimisation problem

All blocks together form one linear program solved by HiGHS. The objective is the yearly cost (terms of blocks that
are not in the scenario are zero):

$$
\min \; \sum_t \Big( c^{gas}_t G_t + c^{el}_t E_t - p^{exp}_t X_t + c^{VOM} E^{CHP}_t + c^{dump} D_t + c^{vent} V_t
+ VOLL_{h} U^{h}_t + VOLL_{c} U^{c}_t + \pi\,(Q^{B}_t + E_t) \Big)
\;+\; a_{B}\, Q_B^{\,*} \;+\; a_{S}\, S^{*} \;+\; a_{CHP}\, P_{CHP}^{\,*}
$$

| Symbol | Meaning | Block |
|---|---|---|
| $G_t$, $c^{gas}_t$ | gas use of all units [MW], gas price + carbon levy [EUR/MWh] | 3 |
| $E_t$, $c^{el}_t$ | grid import [MW], electricity price + tariff adder [EUR/MWh] | 4 |
| $X_t$, $p^{exp}_t$ | grid export [MW], export price [EUR/MWh] (revenue) | 10 |
| $E^{CHP}_t$, $c^{VOM}$ | CHP electricity [MW], variable O&M [EUR/MWh_el] | 9 |
| $D_t$, $V_t$ | heat dumped [MW], CO2 vented [t/h] (cost 0 by default) | 8 |
| $U^h_t$, $U^c_t$ | unserved heat [MW] and CO2 [t/h], penalised at VOLL | 8 |
| $\pi\,(Q^B_t + E_t)$ | CHP priority weight on boiler heat and grid import, **not a cost** (S1 only) | 11 |
| $a_B Q_B$, $a_S S$, $a_{CHP} P_{CHP}$ | annualised capex of boiler, storage and CHP | 5, 6, 9 |

\* The capex terms enter the objective only when the size is a decision variable (`OPTIMISE_BOILER`, `OPTIMISE_TES`,
`OPTIMISE_CHP`). With fixed sizes they are computed after the solve and added to "Total annualised cost".
`summarise()` checks that the solver objective equals the cost recomputed from the hourly flows (plus the priority
weight, which is never reported as a cost).

## Analysis on top of the blocks
[`analysis.py`](../../src/ghmodel/analysis.py) compares runs: `storage_value` (same scenario without storage),
`financial_analysis` (payback, NPV, IRR of the equipment against a reference run, with replacements, salvage value and
a first-order sensitivity) and `compare_scenarios` (KPI tables side by side).

## Where things are computed

| Step | File |
|---|---|
| Read and check the input, daily to hourly | `data.py` (`load_inputs`, `daily_to_hourly`) |
| Automatic sizes, annualised cost factors, hourly marginal costs | `sizing.py` (`resolve_sizes`, `annuity`) |
| Blocks | `blocks.py` |
| Solve (CO2 capacity check, applies `add_custom_constraints`) | `workflow.py` (`solve`, `run_scenario`) |
| Hourly results, balance check, KPIs (same layout for every scenario) | `results.py` |
| Storage value, financial analysis, scenario comparison | `analysis.py` |
