# Block 2: Greenhouse demands (`add_greenhouse_loads`)

**Function**: `add_greenhouse_loads(n, data)` in [`blocks.py`](../../src/ghmodel/blocks.py)

## Purpose
Represents the greenhouse itself: its hourly need for heat, electricity and CO2. These demands are fixed inputs,
the model must cover them every hour.

## Components created
| Component | Type | Bus | Value |
|---|---|---|---|
| `GH heat demand` | Load | `heat` | `data.heat_demand_MW` |
| `GH elec demand` | Load | `elec` | `data.elec_demand_MW` |
| `GH CO2 demand` | Load | `co2` | `data.co2_demand_t_h` |

## Parameters
| Parameter | Default | Unit | Meaning |
|---|---|---|---|
| `greenhouse_area_m2` | 10,000 | m² | only used for specific KPIs (EUR/m², kWh/m²) |

## Inputs
Hourly series from the Excel file, converted by `load_inputs` (see `INPUT_COLUMNS` in `config.py`):

| Internal column | Excel header | Conversion |
|---|---|---|
| `heat_demand_MW` | `heat_demand_kW` | × 1e-3 |
| `elec_demand_MW` | `elec_demand_kW` | × 1e-3 |
| `co2_demand_t_h` | `co2_demand_kg_h` | × 1e-3 |

Checks in `load_inputs`: no missing values, no negative demand, strictly hourly or daily steps, full year
(warning otherwise). With daily input the demand columns are daily totals spread evenly over 24 h.

## Outputs
| Where | Name |
|---|---|
| hourly `r` | `heat_demand`, `elec_demand`, `co2_demand` |
| KPI table | "Heat demand" [MWh/y], "Electricity demand" [MWh/y], "CO2 demand" [t/y] |
| input overview | annual totals, peaks, specific heat demand [kWh/m²/y] |

## Constraints tied to this block
A Load is a fixed withdrawal from its bus. Through the bus balance (block 1), each hour:

$$\text{supply}_{b,t} = d_{b,t} + \text{other outflows}_{b,t} \qquad b \in \{heat, elec, co2\}$$

There is no flexibility: demand cannot be shifted or reduced. If supply is not possible, only the slack generators
of block 8 can close the balance (at a high penalty).

## Assumptions
- Demand is perfectly known for the whole year (perfect foresight).
- CO2 demand is the dosing demand of the crop, independent of whether the boiler runs.
- Daily input gives a flat profile within each day (no day/night pattern).

## Tests
`test_all_demand_is_met`, `test_missing_column_raises`, `test_daily_input_is_spread_over_24h`,
`test_resolution_from_row_count_and_leap_years`, `test_partial_year_warns`.
