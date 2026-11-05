# thermal_storage: heat storage (hot water tank)

**Network** (`block.py`): a PyPSA `Store` named `heat_store` on its own bus, a charging link `heat_charger` from the
bus `heat` and a discharging link `heat_discharger` back to it. It charges from what gives heat to the heat bus
(the gas boiler, the heat pump) and gives back to the greenhouse only (thesis.md A5). It needs a heat source: the gas
boiler or the heat pump (`needs_one_of` in `common/blocks.json`). For a size E in kWh of heat, at each step t:

    stored_t = (1 - loss_t)^dt x stored_t-1 + dt x (eta_charge x charge_t - discharge_t / eta_discharge)
    0 <= stored_t <= E,   charge_t <= p x E,   discharge_t <= p x E      (kW of heat in and out)
    cyclic over the year

**Heat loss** `loss_t`, the share of the stored heat lost per hour (`loss.mode`):

| Mode | Loss per hour |
|---|---|
| `constant` (default) | `constant_per_hour` all year |
| `seasonal` | `seasonal_per_hour.winter` (Dec to Feb), `spring` (Mar to May), `summer` (Jun to Aug), `autumn` (Sep to Nov) |
| `dynamic` | `loss_per_hour_at_ref x (store_temp_c - T_out,t) / (store_temp_c - ref_outside_temp_c)`, at least 0, with the outside temperature of the block's input file, step by step |

**Input file** (its own, only for the dynamic loss): the outside temperature, column `Outside temperature (C)` (role
`outside_temp_c`), °C, any step (an hourly file is repeated in each quarter hour). The heat pump's dynamic COP reads
the same column, so both can use the same file.

**Parameters** (`params/thermal_storage/default.json`), all TO CHECK placeholders:

| Key | Default | What it is |
|---|---|---|
| `charge_efficiency` | 0.95 | share of the heat sent to the tank that is stored |
| `discharge_efficiency` | 0.95 | share of the stored heat that reaches the greenhouse |
| `power_kw_per_kwh` | 0.25 | most heat in, and out, per hour per kWh of size (full in 4 hours) |
| `loss.constant_per_hour` | 0.005 | 0.5 % of the heat stored per hour |
| `loss.seasonal_per_hour` | 0.006, 0.005, 0.004, 0.005 | winter, spring, summer, autumn |
| `loss.dynamic` | 0.005 at 10 °C outside, tank at 70 °C | the dynamic model's reference |

Its money is in `general/commercial`: `capex.thermal_storage_per_kwh` (30 EUR per kWh),
`capex.thermal_storage_fixed_om_per_kwh_year` (0.3 EUR), `finance.thermal_storage_life_yr` (25 years). All TO CHECK.

**Size** (`system/joint.py`, `system/README.md`): always from the joint sizing, one optimisation with the other sized
blocks for the site's lowest yearly cost, unless the case fixes it (`blocks.thermal_storage.sizing`: `{"objective":
"custom", "custom_kwh": X}`, 0 = no tank).

**Study** (`study.py`, `from_joint`): the tank's year in the system at its joint size, set against the cheapest
system without it (its "with and without", `system/effects.py`: the rest sized again together), line by line of the
site's yearly cost, so a tank that shifts the heat pump's electricity to cheaper hours is valued for its effect on
the grid bill too. Written: heat stored and given back, losses, heat released and gas with and without storage, per
month, and the summary. Without a gas boiler the gas columns are left out.

**Assumptions** (thesis.md section 5): A5 (discharges to the greenhouse only), A16 (always sized together with the
other sized blocks, so a tank that lets the boiler be smaller is valued for it), A18 (the dynamic loss uses a fixed
tank temperature).
