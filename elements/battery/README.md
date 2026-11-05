# battery: the battery, its study and the battery check

**Network** (`block.py`, `tech.py`): a store `battery_store` with a charge link `bat_charger` and a discharge link
`bat_discharger` on the bus `main`. For a size S kWh bought: state-of-charge window S x (soc_max - soc_min), power
S x C-rate; the ancillary reserve (a share of the window and the same share of the power) is kept out of the dispatch.
Efficiencies each way, self-discharge per hour, cyclic over the year.

**Study** (`sizing.py`, `study.py`, the reference model's pipeline): the year without battery, a sweep over battery
sizes (each solved for the whole year; a CH size whose DUP crosses into the other regime is solved twice more), the
choice by lifetime profit, payback or a custom size, then the chosen size's bills, monthly tables, value split and
the payback table with Voltiris. With a heat pump the battery also changes when it runs, so its yearly value counts
the gas and CO2 bought it saves against the year without battery (thesis.md A24). In a run the study is used twice:
at the joint size, for the battery's tables, and as the sweep of the battery check.

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

**Joint sizing** (always, `system/README.md`): the size comes from one optimisation with the other sized blocks, for
the site's lowest yearly cost, at most the subsidised maximum (with `cap_at_subsidy_size` and a threshold subsidy)
or else the largest size of `sweep_kwh`; the battery is kept only if the site is still cheaper with its EMS costs.
This study then runs at that size for its tables. The objective `custom` with `custom_kwh` fixes the size (0: no
battery).

**Battery check** (`system/battery_check.py`, when the model sizes the battery): this study's sweep sizes the
battery again with the settings above (`objective` profit or payback, `sweep_kwh`, `fine_grid_kwh`,
`cap_at_subsidy_size`) and the other blocks at their joint sizes, and the two sizes are set side by side. The sweep
keeps the highest lifetime profit (or shortest payback) over the battery life, first purchase only; the joint sizing
the site's lowest yearly cost, with replacements over the PV life, so the sizes may differ. `"system":
{"battery_check": false}` skips it. In the Geneva example (`examples/blocks/case_blocks_CH.json`) both give
2,495 kWh, the subsidised maximum.
