# Block 9: Gas CHP (`add_chp`)

**Function**: `add_chp(n, P, sizes)` in [`blocks.py`](../../src/ghmodel/blocks.py). Used in Scenario 1.

## Purpose
A gas-engine combined heat and power unit. It burns natural gas and produces electricity, heat and a CO2 stream
for enrichment at the same time. It is the "CHP: gas engine (power, heat, flue-gas CO2)" box of the S1 figure, with
four flows drawn: heat to the greenhouse and to the storage (orange), CO2 to the greenhouse (green), and electricity
to the greenhouse and to the grid (blue).

## Components created
| Component | Type | bus0 → bus1, bus2, bus3 | Efficiencies |
|---|---|---|---|
| `CHP` | Link | `gas` → `elec`, `heat`, `co2` | η_el, η_th, 0.202 × usable fraction |

Capacity `p_nom` is on the gas side: `p_nom = electrical capacity / η_el`.

## Parameters
| Parameter | Default | Unit | Meaning |
|---|---|---|---|
| `chp_capacity_MW_el` | `None` | MW_el | fixed size; `None` → automatic (below) |
| `chp_heat_share_of_peak` | 0.5 | – | automatic size: CHP thermal capacity = this share × peak heat demand `[placeholder]` |
| `chp_eta_el` | 0.42 | – (LHV) | electricity out / fuel in `[placeholder]` |
| `chp_eta_th` | 0.45 | – (LHV) | useful heat out / fuel in `[placeholder]` |
| `chp_co2_usable_fraction` | 1.0 | – | share of exhaust CO2 usable for dosing after flue-gas cleaning `[placeholder]` |
| `chp_capex_EUR_per_kW_el` | 900 | EUR/kW_el | investment `[placeholder]` |
| `chp_lifetime_y` | 15 | years | `[placeholder]` |
| `chp_fom_frac` | 0.02 | share of capex per year | fixed O&M `[placeholder]` |
| `chp_vom_EUR_per_MWh_el` | 12 | EUR/MWh_el | variable maintenance `[placeholder]` |
| `OPTIMISE_CHP` | False | – | True = the size is a decision variable |
| `gas_co2_factor_t_per_MWh` | 0.202 | t/MWh | shared with blocks 3 and 5 |

## Inputs
From `sizing.resolve_sizes`:
- `chp_cap_el` = `chp_capacity_MW_el` or `chp_heat_share_of_peak` × peak heat × η_el / η_th
  (0.51 MW_el for the 1 ha dummy greenhouse)
- `chp_cost_per_MW_el` = capex × (annuity + fixed O&M) = 104,700 EUR per MW_el per year with the defaults

## Outputs
| Where | Name | Formula |
|---|---|---|
| hourly `r` | `chp_gas` [MW fuel] | `p0` |
| hourly `r` | `chp_elec` [MW] | −`p1` = η_el × gas |
| hourly `r` | `chp_heat` [MW] | −`p2` = η_th × gas |
| hourly `r` | `chp_co2` [t/h] | −`p3` = 0.202 × usable × gas |
| hourly `r` | `chp_vom_EUR` | electricity × variable O&M |
| KPI table | "CHP electrical capacity", "CHP thermal capacity", "Gas to CHP", "CHP electricity output", "CHP full-load hours", "CHP electricity used on site", "CHP heat output", "CO2 from CHP", "CHP variable O&M", "Annualised capex + fixed O&M: CHP" | |

## Constraints tied to this block
With $G_t$ the gas taken by the CHP and $P$ its fuel-side capacity:

| Constraint | Equation |
|---|---|
| Electricity | $E^{CHP}_t = \eta_{el}\, G_t$ |
| Heat | $Q^{CHP}_t = \eta_{th}\, G_t$ (fixed heat-to-power ratio η_th/η_el ≈ 1.07) |
| CO2 | $C^{CHP}_t = 0.202 \cdot f_{usable}\, G_t$ |
| Capacity | $0 \le G_t \le P$ (no minimum load, no start-up cost, no ramp limit) |
| Size, fixed | $P = P^{el} / \eta_{el}$ |
| Size, `OPTIMISE_CHP` | $P \ge 0$ is a variable; the objective gets $a_{CHP}\,\eta_{el}\,P$ (= $a_{CHP}$ per MW_el) |
| Objective | $+\; c^{VOM}\,\eta_{el}\, G_t$ (variable O&M), the gas cost is counted in block 3 |

Electricity, heat and CO2 are linked: the CHP cannot produce heat without producing electricity and CO2. Surplus
electricity is exported (block 10), surplus heat goes to the storage or the heat dump, surplus CO2 is vented (block 8).

## Assumptions
- Back-pressure type: fixed ratios, constant efficiencies at every load.
- Pure LP: the CHP can run at any part load, including very low loads, and can switch on and off every hour.
  Real gas engines have a minimum load (about 50 %) and start-up costs.
- All exhaust CO2 is usable (`chp_co2_usable_fraction` = 1.0, placeholder). Real engines need a catalyst to remove
  NOx and ethylene before the CO2 can be dosed.
- The automatic size (50 % of peak heat) is a placeholder; real CHP sizing in greenhouses is often driven by the
  lighting load or by the grid connection.

## Tests
`test_s1_demand_met_and_chp_conversion`, `test_s1_chp_has_priority`, `test_s1_financials_vs_baseline`.
