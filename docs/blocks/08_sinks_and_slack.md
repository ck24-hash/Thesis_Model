# Block 8: Heat dump, CO2 vent and slack (`add_sinks_and_slack`)

**Function**: `add_sinks_and_slack(n, P)` in [`blocks.py`](../../src/ghmodel/blocks.py)

## Purpose
**None of these flows are drawn in the scenario figure: they are modelling assumptions.**
- The **heat dump** and **CO2 vent** let surplus heat and CO2 leave the system. They are needed because the boiler
  produces heat and CO2 in a fixed ratio: when the greenhouse needs CO2 but little heat (summer), the extra heat
  must go somewhere, and when it needs heat but little CO2 (winter night), the extra CO2 must be vented.
- The **unserved heat** and **unserved CO2** generators are slack variables. They keep the problem feasible if
  demand cannot be met, at a very high cost. In a valid result they are 0.

## Components created
| Component | Type | Bus | sign | Capacity | Cost |
|---|---|---|---|---|---|
| `Heat dump` | Generator (sink) | `heat` | −1 | 10,000 MW | `heat_dump_cost_EUR_per_MWh` |
| `CO2 vent` | Generator (sink) | `co2` | −1 | 10,000 t/h | `co2_vent_cost_EUR_per_t` |
| `Unserved heat` | Generator | `heat` | +1 | 10,000 MW | `voll_heat_EUR_per_MWh` |
| `Unserved CO2` | Generator | `co2` | +1 | 10,000 t/h | `voll_co2_EUR_per_t` |

## Parameters
| Parameter | Default | Unit | Meaning |
|---|---|---|---|
| `heat_dump_cost_EUR_per_MWh` | 0.0 | EUR/MWh | cost of rejecting heat (0 = free, current assumption) |
| `co2_vent_cost_EUR_per_t` | 0.0 | EUR/t | cost of venting CO2 (0 = free, current assumption) |
| `voll_heat_EUR_per_MWh` | 1,000 | EUR/MWh | penalty for unserved heat |
| `voll_co2_EUR_per_t` | 5,000 | EUR/t | penalty for unserved CO2 |

## Inputs
None besides the parameters.

## Outputs
| Where | Name |
|---|---|
| hourly `r` | `heat_dump`, `co2_vent`, `heat_unserved`, `co2_unserved`, `sink_cost_EUR` |
| KPI table | "Heat dumped (rejected)", "Heat dumped / boiler output", "CO2 vented (excess)", "Unserved heat", "Unserved CO2", "Heat dump + CO2 vent cost" |
| checks | `check_balances` warns if unserved heat or CO2 is above zero |

## Constraints tied to this block
| Constraint | Equation |
|---|---|
| Bounds | $0 \le D_t, V_t, U^h_t, U^c_t \le 10\,000$ |
| Heat bus (with block 1) | $\ldots + U^h_t = \ldots + D_t$ |
| CO2 bus (with block 1) | $\ldots + U^c_t = \ldots + V_t$ |
| Objective terms | $c^{dump} D_t + c^{vent} V_t + VOLL_h U^h_t + VOLL_c U^c_t$ |

## Assumptions
- Heat can be rejected and CO2 vented without limit and, by default, at no cost. A cost can be set later.
- Unserved demand is penalised, not forbidden. When the boiler size is optimised, a peak that is used for very few
  hours could in theory be left unserved if that is cheaper than boiler capacity (1 MW of boiler costs about 8,019
  EUR/y, so this happens if the top MW would serve less than about 8 MWh a year). It does not happen on the dummy data,
  but the KPI "Unserved heat" must be checked with real data.

## Tests
`test_all_demand_is_met`, `test_heat_is_dumped_only_when_needed_for_co2`,
`test_undersized_boiler_gives_unserved_demand_and_warning`, `test_dump_cost_enters_objective_and_reduces_dump`.
