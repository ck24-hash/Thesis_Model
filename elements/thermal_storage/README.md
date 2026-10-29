# thermal_storage: heat storage (hot water tank)

**Network** (`block.py`): a PyPSA `Store` named `heat_store` on its own bus, a charging link `heat_charger` from the
bus `heat` and a discharging link `heat_discharger` back to it. It charges from what gives heat to the heat bus
(today the gas boiler) and gives back to the greenhouse only (thesis.md A5). It needs the gas boiler. For a size E in
kWh of heat, at each step t:

    stored_t = (1 - loss_t)^dt x stored_t-1 + dt x (eta_charge x charge_t - discharge_t / eta_discharge)
    0 <= stored_t <= E,   charge_t <= p x E,   discharge_t <= p x E      (kW of heat in and out)
    cyclic over the year

**Heat loss** `loss_t`, the share of the stored heat lost per hour (`loss.mode`):

| Mode | Loss per hour |
|---|---|
| `constant` (default) | `constant_per_hour` all year |
| `seasonal` | `seasonal_per_hour.winter` (Dec to Feb), `spring` (Mar to May), `summer` (Jun to Aug), `autumn` (Sep to Nov) |
| `dynamic` | `loss_per_hour_at_ref x (store_temp_c - T_out,t) / (store_temp_c - ref_outside_temp_c)`, at least 0, with the outside temperature of the block's input file, hour by hour |

**Input file** (its own, only for the dynamic loss): the outside temperature, column `Outside temperature (C)` (role
`outside_temp_c`), °C, any step (an hourly file is repeated in each quarter hour).

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

**Study** (`sizing.py`, `study.py`), the battery's logic, with the boiler fixed at the size its study chose:

1. The year without storage (the boiler study's chosen year): its running cost (gas, carbon levy, boiler variable
   O&M) is the baseline.
2. The sizes: the case's list, or 1, 2, 4, 8 and 12 hours of the boiler at full output, rounded up to 100 kWh.
3. Each size is optimised over the whole year. Yearly value = running cost saved - the storage's fixed O&M;
   investment; payback = investment / value; lifetime profit = value x life - investment.
4. The choice: `profit` (highest lifetime profit among the sizes that pay back within the storage life, else the
   shortest payback; default), `payback`, or `custom` (closest to `custom_kwh`, which is added to the list).
5. The chosen size is fixed for the battery study (`s.storage_kwh`).

**Settings** (case file, `blocks.thermal_storage.sizing`): `objective`, `sizes_kwh` (empty = automatic),
`custom_kwh`.

**Assumptions** (thesis.md section 5): A5 (discharges to the greenhouse only), A16 (sized together with the boiler by
default; sized one at a time, after the boiler and with it fixed, it can only save heat the boiler would release and
shift gas between days), A18 (the dynamic loss uses a fixed tank temperature).

**Joint sizing** (the default with two sized blocks or more, `system/README.md`): the size comes from one optimisation
with the other sized blocks, for the site's lowest yearly cost; this study then runs at that size for its tables. The
settings above apply with `"system": {"sizing": "sequential"}`, or when this is the only sized block; the objective
`custom` fixes the size in both.
