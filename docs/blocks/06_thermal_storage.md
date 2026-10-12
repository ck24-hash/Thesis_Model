# Block 6: Thermal storage (`add_thermal_storage`)

**Function**: `add_thermal_storage(n, P, sizes)` in [`blocks.py`](../../src/ghmodel/blocks.py)

## Purpose
A hot-water buffer tank. It stores boiler heat when it is not needed (for example heat produced during the day
together with CO2) and releases it later (for example at night). It is the "Thermal storage" box of the figure.

## Components created
```
heat bus --[TES charge, ηc]--> tes bus (Store "TES") --[TES discharge, ηd]--> heat bus
```
| Component | Type | Connection | Capacity |
|---|---|---|---|
| `TES charge` | Link | `heat` → `tes`, efficiency ηc | `p_nom` = storage power (heat-bus side) |
| `TES discharge` | Link | `tes` → `heat`, efficiency ηd | `p_nom` = storage power / ηd (so delivered heat ≤ storage power) |
| `TES` | Store | `tes` | `e_nom` = storage capacity [MWh] |

## Parameters
| Parameter | Default | Unit | Meaning |
|---|---|---|---|
| `tes_capacity_MWh` | `None` | MWh | fixed capacity; `None` → hours × peak heat demand |
| `tes_hours_of_peak` | 6 | h | used when the capacity is automatic |
| `tes_power_MW_th` | `None` | MW | fixed power; `None` → boiler thermal capacity |
| `tes_hours_at_full_power` | 4.0 | h | power ≤ capacity / these hours; `None` = off `[placeholder]` |
| `tes_min_soc_frac` | 0.1 | share of capacity | reserve that is never used; 0 = off `[placeholder]` |
| `tes_eta_charge` | 0.98 | – | `[placeholder]` |
| `tes_eta_discharge` | 0.98 | – | `[placeholder]` |
| `tes_standing_loss_per_h` | 0.001 | share of stored energy per h | heat loss to ambient `[placeholder]` |
| `tes_capex_EUR_per_kWh` | 10 | EUR/kWh | `[placeholder]` |
| `tes_lifetime_y` | 25 | years | |
| `tes_fom_frac` | 0.01 | share of capex per year | fixed O&M |
| `OPTIMISE_TES` | False | – | True = the capacity is a decision variable |
| `tes_capacity_max_MWh` | `None` | MWh | optional upper bound when optimised |

## Inputs
From `sizing.resolve_sizes`:
- `tes_cap` = `tes_capacity_MWh` or 6 h × peak heat demand
- `tes_power` = min(`tes_power_MW_th` or boiler capacity, `tes_cap` / `tes_hours_at_full_power`)
- `tes_cost_per_MWh` = capex × (annuity + fixed O&M) = 809.5 EUR per MWh per year with the defaults

## Outputs
| Where | Name | Meaning |
|---|---|---|
| hourly `r` | `tes_charge` [MW] | heat taken from the heat bus |
| hourly `r` | `tes_discharge` [MW] | heat delivered to the heat bus |
| hourly `r` | `tes_soc` [MWh] | stored energy at the end of the hour |
| KPI table | "Thermal storage capacity", "Energy discharged from storage", "Equivalent full cycles" (discharged / capacity), "Storage losses (charge + standing + discharge)", "Annualised capex + fixed O&M: storage" | |

## Constraints tied to this block
With $ch_t$ the heat charged, $dis_t$ the energy taken out of the store, $e_t$ the stored energy, $S$ the capacity
and $P^{S}$ the power:

| Constraint | Equation |
|---|---|
| Energy balance of the store | $e_t = (1-\lambda)\, e_{t-1} + \eta_c\, ch_t - dis_t$ |
| Heat delivered | $Q^{dis}_t = \eta_d\, dis_t$ |
| Cyclic year | $e_0$ is linked to $e_{T}$ (same level at the start and end of the year, no free initial heat) |
| Capacity and reserve | $f_{min}\, S \le e_t \le S$ |
| Charge power | $0 \le ch_t \le P^{S}$ |
| Discharge power | $0 \le \eta_d\, dis_t \le P^{S}$ |
| Power linked to capacity, fixed sizes | $P^{S} = \min(P^{S}_{given},\, S / h)$ (in `sizing.py`) |
| Power linked to capacity, `OPTIMISE_TES` | $h\,P^{S}_{ch} \le S$ and $h\,\eta_d P^{S}_{dis} \le S$ (block 7) |
| Size, `OPTIMISE_TES` | $0 \le S \le S^{max}$ is a variable; the objective gets $a_S\, S$ |

Simultaneous charge and discharge is not forbidden, but losses make it unattractive (checked: 0 hours on the dummy data).

## Assumptions
- One-node storage at a single temperature (no stratification, no temperature limits).
- The reserve still has standing losses, which the boiler has to make up.
- Discharged heat returns to the shared heat bus, so it could in theory also reach the heat dump (not drawn;
  never optimal, accepted simplification).
- When optimised, the charge/discharge links have no own cost; their size only follows from the power/capacity link.

## Tests
`test_storage_optimisation_is_not_worse_than_fixed_size` (incl. power ≤ capacity / h),
`test_ramp_limit_and_storage_reserve_hold`, `test_technical_constraints_can_be_switched_off`.
