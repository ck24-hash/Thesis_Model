# Block 5: Natural gas boiler (`add_ng_boiler`)

**Function**: `add_ng_boiler(n, P, sizes)` in [`blocks.py`](../../src/ghmodel/blocks.py)

## Purpose
Burns natural gas to produce heat for the greenhouse and a flue-gas CO2 stream for enrichment. It is the
"Conventional boiler" of the figure, with two outputs drawn: heat (orange) and CO2 (green).

## Components created
| Component | Type | bus0 → bus1, bus2 | Efficiencies |
|---|---|---|---|
| `NG boiler` | Link | `gas` → `heat`, `co2` | `efficiency` = η, `efficiency2` = 0.202 × usable fraction |

Capacity `p_nom` is on the gas side: `p_nom = thermal capacity / η`.

## Parameters
| Parameter | Default | Unit | Meaning |
|---|---|---|---|
| `boiler_eta` | 0.92 | – (LHV) | heat out / fuel in `[placeholder]` |
| `boiler_capacity_MW_th` | `None` | MW_th | fixed size; `None` → margin × peak heat demand |
| `boiler_sizing_margin` | 1.2 | – | used when the size is automatic |
| `boiler_co2_usable_fraction` | 1.0 | – | share of flue-gas CO2 that reaches the greenhouse `[placeholder]` |
| `boiler_ramp_limit_per_h` | 0.5 | share of capacity per h | max change of output from one hour to the next; `None` = off `[placeholder]` |
| `boiler_capex_EUR_per_kW_th` | 80 | EUR/kW_th | investment `[placeholder]` |
| `boiler_lifetime_y` | 20 | years | |
| `boiler_fom_frac` | 0.02 | share of capex per year | fixed O&M |
| `OPTIMISE_BOILER` | False | – | True = the size is a decision variable |
| `gas_co2_factor_t_per_MWh` | 0.202 | t/MWh | shared with block 3 |
| `discount_rate` | 0.05 | – | for the annuity |

## Inputs
From `sizing.resolve_sizes`:
- `boiler_cap_th` = `boiler_capacity_MW_th` or 1.2 × peak heat demand [MW_th]
- `boiler_cost_per_MW` = capex × (annuity + fixed O&M) = 8,019 EUR per MW_th per year with the defaults

$$a_B = capex \times \Big(\frac{r}{1-(1+r)^{-n}} + f_{O\&M}\Big)$$

Before solving, `workflow.check_co2_capacity` warns if all fixed-size units feeding the CO2 bus together (boiler, and
CHP in S1) cannot deliver the CO2 peak: max CO2 = Σ fuel capacity × CO2 efficiency.

## Outputs
| Where | Name | Formula |
|---|---|---|
| hourly `r` | `boiler_gas` [MW fuel] | `p0` (`gas_use` = boiler + CHP fuel) |
| hourly `r` | `boiler_heat` [MW] | −`p1` = η × gas use |
| hourly `r` | `boiler_co2` [t/h] | −`p2` = 0.202 × usable × gas use |
| KPI table | "Boiler thermal capacity", "Boiler heat output", "Annualised capex + fixed O&M: boiler" | |
| KPI table | "Gas to boiler", "CO2 from boiler" | |
| KPI table | "Gas equivalent of dumped heat (boiler efficiency)", "Cost of gas for dumped heat (boiler efficiency)" | heat dump / η (× gas price) |
| heat balance | "Heat produced (CHP + boiler)" split into from CHP / from boiler, direct, into storage, dumped | |

## Constraints tied to this block
With $G_t$ the gas taken by the boiler and $P$ its fuel-side capacity:

| Constraint | Equation |
|---|---|
| Conversion to heat | $Q_t = \eta\, G_t$ |
| Conversion to CO2 | $C_t = 0.202 \cdot f_{usable}\, G_t$ (heat and CO2 are locked together: about 0.22 t CO2 per MWh of heat) |
| Capacity | $0 \le G_t \le P$ (one direction only, no minimum load) |
| Ramp limit (if not `None`) | $-r\,P \le G_t - G_{t-1} \le r\,P$ for every hour after the first |
| Size, fixed | $P = Q^{cap} / \eta$ |
| Size, `OPTIMISE_BOILER` | $P \ge 0$ is a variable; the objective gets $a_B\,\eta\,P$ (= $a_B$ per MW_th) |

When the size is optimised the 1.2 margin and `boiler_capacity_MW_th` are ignored, and the reported capacity is
$P \times \eta$.

## Assumptions
- The boiler is the whole heating system (no separate backup is drawn).
- Constant efficiency at every load, no minimum load, no start-up cost (pure LP).
- All flue-gas CO2 can be used for dosing (`boiler_co2_usable_fraction` = 1.0, placeholder).
- The heat/CO2 coupling is why heat is dumped in summer: gas is burnt for CO2 when little heat is needed.

## Tests
`test_gas_and_heat_are_consistent`, `test_heat_is_dumped_only_when_needed_for_co2`,
`test_undersized_boiler_gives_unserved_demand_and_warning`, `test_ramp_limit_and_storage_reserve_hold`,
`test_technical_constraints_can_be_switched_off`.

## Role in Scenario 1 (backup boiler)
The same block is the **backup boiler** of S1, with the same parameters (default size 1.2 × peak heat, i.e. a full
backup able to cover the greenhouse if the CHP is off). With `chp_priority = True` (block 11) its heat carries a dispatch
weight of `priority_penalty_EUR_per_MWh`, so it only runs when the CHP is at full capacity.

## Notes for S2 to S4
In S2/S3 the same block can be reused as the backup boiler and CO2 source. The component name is fixed
(`NG boiler`), so a second boiler of another type would need a name argument.
