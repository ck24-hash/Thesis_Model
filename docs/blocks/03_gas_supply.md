# Block 3: Natural gas supply (`add_gas_supply`)

**Function**: `add_gas_supply(n, sizes)` in [`blocks.py`](../../src/ghmodel/blocks.py)

## Purpose
Delivers natural gas to the site at an hourly price. It is the "Fuel supply: Natural gas" box of the figure.

## Components created
| Component | Type | Bus | Capacity | Cost |
|---|---|---|---|---|
| `NG supply` | Generator | `gas` | 10,000 MW (not binding) | `sizes.gas_marginal` [EUR/MWh] |

## Parameters
| Parameter | Default | Unit | Meaning |
|---|---|---|---|
| `gas_co2_factor_t_per_MWh` | 0.202 | t CO2/MWh (LHV) | CO2 released per MWh of gas burnt |
| `co2_price_EUR_per_t` | `None` | EUR/t CO2 | carbon levy on gas burnt; `None` → country default |
| `country` | "CH" | – | selects the default levy in `COUNTRY_DEFAULTS` (CH 125, FR 44.6, NL 0 EUR/t, placeholders) |

## Inputs
| Input | Source |
|---|---|
| `gas_price_EUR_MWh` (hourly) | Excel column `gas_price_EUR_per_MWh`, LHV, all-in **except** the carbon levy |

The hourly marginal cost is computed in `sizing.resolve_sizes`:

$$c^{gas}_t = p^{gas}_t + \text{levy} \times 0.202$$

## Outputs
| Where | Name | Formula |
|---|---|---|
| hourly `r` | `gas_cost_EUR` | gas use × gas price |
| hourly `r` | `co2_levy_EUR` | gas use × 0.202 × levy |
| hourly `r` | `emissions_gas_t` | gas use × 0.202 |
| KPI table | "Gas consumption", "Gas cost", "CO2 levy on gas", "Direct CO2 (gas combustion)" | annual sums |

Gas use `r.gas_use` = boiler fuel + CHP fuel (`r.boiler_gas`, `r.chp_gas`); the KPI table also shows "Gas to CHP"
and "Gas to boiler". The levy and the emissions apply to all gas burnt.

## Constraints tied to this block
$$0 \le G_t \le 10\,000 \text{ MW}$$
and the `gas` bus balance: $G_t$ = fuel taken by the boiler (+ the CHP in S1). The cost $c^{gas}_t G_t$ enters the objective.

## Assumptions
- **Unlimited gas supply** (no connection capacity limit). Not drawn as a limit, flagged in the code.
- Gas price is LHV and all-in except the carbon levy, which is added separately (confirmed by the user).
- **All CO2 from burning gas counts as emitted**, including the part dosed into the greenhouse (no credit for crop uptake).

## Tests
`test_country_defaults_and_override`.
