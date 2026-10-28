# battery: the battery, its sizing and its payback

**Network** (`block.py`, `tech.py`): a store `battery_store` with a charge link `bat_charger` and a discharge link
`bat_discharger` on the bus `main`. For a size S kWh bought: state-of-charge window S x (soc_max - soc_min), power
S x C-rate; the ancillary reserve (a share of the window and the same share of the power) is kept out of the dispatch.
Efficiencies each way, self-discharge per hour, cyclic over the year.

**Money** (`block.py`, `ems.py`): price per kWh by size (tiers, linear in between), subsidy (percent, fixed, or up to a
threshold size; CH's OCAN rule sets the threshold from the yearly load), replacements over the horizon (the PV life)
at a share of the gross price, EMS fixed cost, fees and hardware, ancillary revenue = reserved kW x rate.

**Study** (`sizing.py`, `study.py`, the reference model's pipeline): the year without battery, a sweep over battery
sizes (each solved for the whole year; a CH size whose DUP crosses into the other regime is solved twice more), the
choice by lifetime profit, payback or a custom size, then the chosen size's bills, monthly tables, value split and
the payback table with Voltiris.

Parameters (`params/`, from the reference model's files):

| Group | Values |
|---|---|
| `tech/default.json` | C-rate 0.5, efficiency 97% each way, SoC 10 to 90%, self-discharge 0.1% per day |
| `capex/default.json` | 400 CHF/kWh flat, replacements at 60% of the gross price |
| `finance/default.json` | battery life 10 years |
| `ems/default.json` | 2,500 CHF per year, 1,000 EUR hardware, fees 0% |
| `ancillary/<country>.json` | 25% of the battery kept for grid services; CH 90 CHF/kW/yr, NL and FR 98.1 EUR/kW/yr |
| `subsidies/<country>/...` | `battery`: CH GE 75% up to the OCAN size, NL 0%, FR 50% (FR to confirm, as in the reference) |

Ancillary services are always applied; to leave them out of a run, set
`{"ancillary": {"rate_per_kw_year": 0, "reserve": {"mode": "percent", "frac": 0}}}` in its overrides.
