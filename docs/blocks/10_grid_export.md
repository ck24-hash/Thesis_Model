# Block 10: Grid export (`add_grid_export`)

**Function**: `add_grid_export(n, sizes)` in [`blocks.py`](../../src/ghmodel/blocks.py). Used in Scenario 1.

## Purpose
Sells surplus electricity to the grid. It is the arrow from the CHP to "Electricity grid: Import and export" in the
S1 figure. **Exported electricity is a revenue**: it lowers the objective and is shown as an income in all cost tables.

## Components created
| Component | Type | Bus | sign | Capacity | Cost |
|---|---|---|---|---|---|
| `Grid export` | Generator (sink) | `elec` | −1 | `sizes.export_limit` [MW] | `sizes.export_marginal` = − export price [EUR/MWh] |

## Parameters
| Parameter | Default | Unit | Meaning |
|---|---|---|---|
| `grid_export_limit_MW` | `None` | MW | export connection limit; `None` → 10,000 MW (not binding) |

## Inputs
| Input | Source |
|---|---|
| `elec_export_price_EUR_MWh` (hourly) | **new Excel column** `elec_export_price_EUR_per_MWh` (optional column in `config.OPTIONAL_COLUMNS`, required by S1) |

With daily input the export price is repeated in every hour of the day (like the other prices). The block raises a
`KeyError` if the column is missing, and warns if the export price is above the import price in some hour.

Example input file: `data/s1_input_data_EXAMPLE_dummy.xlsx` (dummy export price ≈ 0.7 × import price − 10 EUR/MWh,
always below the import price).

## Outputs
| Where | Name | Formula |
|---|---|---|
| hourly `r` | `grid_export`, `export_price` | |
| hourly `r` | `export_revenue_EUR` | export × export price |
| hourly `r` | `export_co2_credit_t` | export × grid emission factor (information only) |
| KPI table | "Grid export", "Electricity export revenue (income)", "Grid CO2 displaced by export (info, not subtracted)" | |

The revenue is subtracted in "Operating cost (OPEX, net of export revenue)".

## Constraints tied to this block
$$0 \le X_t \le X^{max}$$
and the `elec` bus balance: $E^{import}_t + E^{CHP}_t = d^{el}_t + X_t$. Objective term: $-\,p^{exp}_t X_t$.

## Assumptions
- The export price is exogenous (price taker); no feed-in limit unless `grid_export_limit_MW` is set.
- Simultaneous import and export is not forbidden (it would need a binary variable). It never pays off as long as
  the export price is below the import price, which the block checks.
- Exported electricity does **not** reduce the reported emissions. The displaced grid CO2 is shown separately for
  information, because crediting it is a methodological choice for the thesis.

## Tests
`test_s1_export_is_revenue`, `test_s1_needs_export_price`.
