# Block 11: CHP priority (`add_chp_priority`)

**Function**: `add_chp_priority(n, P)` in [`blocks.py`](../../src/ghmodel/blocks.py). Used in Scenario 1, called after
the boiler and grid blocks.

## Purpose
Implements the merit order requested for Scenario 1: **the CHP is used before the backup boiler and before grid
import**. A cost-minimising LP only runs the CHP when it is the cheapest option; with low export prices it would
mostly use the boiler instead. This block makes the CHP the first choice.

It adds no component. It adds a **priority penalty** (a dispatch weight, not a real cost) to:
- the heat of the backup boiler (`NG boiler` marginal cost + penalty × η, i.e. penalty per MWh heat),
- grid import (`Grid import` marginal cost + penalty per MWh).

## Parameters
| Parameter | Default | Unit | Meaning |
|---|---|---|---|
| `chp_priority` | True | – | switch; False = pure cost-optimal dispatch |
| `priority_penalty_EUR_per_MWh` | 200 | EUR/MWh | size of the weight; must be below `voll_heat_EUR_per_MWh` (checked in `Params`) so that the boiler is still preferred to unserved heat |

## Inputs / outputs
| Where | Name |
|---|---|
| hourly `r` | `priority_penalty_EUR` = penalty × (boiler heat + grid import) |
| notebook | "Priority penalty in the objective (not a cost)" and section 10.3 "Cost of the CHP priority rule" |

The penalty is **excluded from every reported cost** (OPEX, total annualised cost, financial analysis). It is only
added back in the check that the solver objective equals the recomputed cost.

## Constraints tied to this block
No new constraint. The objective becomes

$$\ldots + \pi \,(Q^{boiler}_t + E^{import}_t)$$

so that, at the optimum, the boiler and grid import are only used when the CHP is at full capacity (verified by
`test_s1_chp_has_priority`). Order of the weights: CHP (no penalty) < boiler / grid import (π = 200) < unserved heat
(VOLL = 1,000 EUR/MWh).

## Assumptions and consequences
- The rule is soft: if CHP electricity would have to be exported at a very negative price, the boiler could still be
  chosen (it never happens with the dummy data).
- Because heat and electricity are coupled, giving the CHP priority for heat also means exporting the surplus
  electricity, even at a loss. On the dummy data (CH, carbon levy 125 EUR/t) the rule raises the total annualised cost
  by about 90 kEUR/y compared with cost-optimal dispatch (section 10.3 of the S1 notebook).

## Tests
`test_s1_chp_has_priority`, `test_s1_priority_off_is_cheaper_or_equal`.
