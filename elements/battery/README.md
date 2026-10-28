# battery: the battery and its sizing study

**Network** (`block.py`, `tech.py`): a store `battery_store` with a charge link `bat_charger` and a discharge link
`bat_discharger` on the bus `main`. For a size S kWh bought: state-of-charge window S x (soc_max - soc_min), power
S x C-rate; the ancillary reserve (a share of the window and the same share of the power) is kept out of the dispatch.
Efficiencies each way, self-discharge per hour, cyclic over the year.

**Study** (`sizing.py`, `study.py`, the reference model's pipeline): the year without battery, a sweep over battery
sizes (each solved for the whole year; a CH size whose DUP crosses into the other regime is solved twice more), the
choice by lifetime profit, payback or a custom size, then the chosen size's bills, monthly tables, value split and
the payback table with Voltiris.

**Settings.** `sizing` in the case's `blocks.battery`: `objective`, `sweep_kwh`, `custom_kwh`, `fine_grid_kwh`,
`fine_window_kwh`, `cap_at_subsidy_size`.

**Parameters** (`params/`, from the reference model's files):

| File | Values |
|---|---|
| `tech/default.json` | C-rate 0.5, efficiency 97% each way, SoC 10 to 90%, self-discharge 0.1% per day |
| `ancillary/<country>.json` | the reserve: 25% of the window and of the power kept for grid services (CH, NL, FR) |

Its price tiers, replacements, life and the reserve's revenue rate are in `general/commercial`, its subsidy in
`general/subsidies`, its EMS costs in `general/ems`. To leave the ancillary services out of a run, set
`{"ancillary": {"rate_per_kw_year": 0, "reserve": {"mode": "percent", "frac": 0}}}` in its overrides.
