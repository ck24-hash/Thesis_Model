# Block 4: Grid import (`add_grid_import`)

**Function**: `add_grid_import(n, sizes)` in [`blocks.py`](../../src/ghmodel/blocks.py)

## Purpose
Buys electricity from the grid at an hourly price. It is the "Electricity grid: Import" box of the figure.
In the Baseline it is the only electricity source, so grid import equals the electricity demand every hour.

## Components created
| Component | Type | Bus | Capacity | Cost |
|---|---|---|---|---|
| `Grid import` | Generator | `elec` | `sizes.grid_limit` [MW] | `sizes.grid_marginal` [EUR/MWh] |

## Parameters
| Parameter | Default | Unit | Meaning |
|---|---|---|---|
| `grid_import_limit_MW` | `None` | MW | connection limit; `None` → 10 × peak electricity demand (not binding) |
| `grid_tariff_adder_EUR_per_MWh` | 0.0 | EUR/MWh | extra tariff on top of the price column |
| `grid_co2_factor_t_per_MWh` | `None` | t CO2/MWh | constant grid emission factor; `None` → country default (CH 0.10, FR 0.05, NL 0.30, placeholders) |

## Inputs
| Input | Source |
|---|---|
| `elec_price_EUR_MWh` (hourly) | Excel column `elec_price_EUR_per_MWh`, all-in import price |
| `grid_ef_t_MWh` (hourly, optional) | Excel column `grid_emission_factor_kg_per_kWh`; if absent, the constant above is used |

Marginal cost: $c^{el}_t = p^{el}_t + \text{tariff adder}$.

## Outputs
| Where | Name | Formula |
|---|---|---|
| hourly `r` | `grid_import`, `elec_price` | |
| hourly `r` | `elec_cost_EUR` | import × (price + adder) |
| hourly `r` | `emissions_grid_t` | import × grid emission factor |
| KPI table | "Grid import", "Grid export" (= 0), "Electricity purchase", "Indirect CO2 (grid import)" | annual sums |

## Constraints tied to this block
$$0 \le E_t \le E^{max}$$
and the `elec` bus balance, which in the Baseline reduces to $E_t = d^{el}_t$. The cost $c^{el}_t E_t$ enters the objective.

In S1 the balance becomes import + CHP electricity = demand + export, and the CHP priority (block 11) adds a dispatch
weight of `priority_penalty_EUR_per_MWh` to every imported MWh (not reported as a cost).

## Assumptions
- Import only in the Baseline; export is a separate block (block 10, S1).
- The default limit is never binding. With a heat pump or data center (S2–S4) the peak demand grows, so the
  limit must be set from the real connection capacity.
- Constant grid emission factor per country unless an hourly column is given.

## Tests
`test_gas_and_heat_are_consistent` (grid import = electricity demand), `test_country_defaults_and_override`.
