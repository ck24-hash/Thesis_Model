# general: what is not a physical block

The blocks in `elements/` hold the technical side of each part of the system. What applies across them is here, one
folder per item, each with a `block.py` (its `ID`, the parameters it owns `OWNS`, `load_params()`, a class) and its own
`params/`. All values come from the reference model's files (`elements/battery_reference/params`).

| Item | What it holds | Parameter files |
|---|---|---|
| `commercial/` | the Voltiris business model (direct sales or EaaS, `business_model.py`), investment prices (Voltiris per Wp, battery price tiers, battery replacements), lifetimes (PV life, also the battery study's horizon; battery life), the revenue rate of the battery's ancillary reserve | `business_models/`, `capex/default.json`, `finance/default.json`, `ancillary/<country>.json` (rate) |
| `subsidies/` | subsidies on the Voltiris modules and on the battery: percent, fixed amount, or percent up to a threshold size (CH's OCAN rule from the yearly load) | `subsidies/<country>/_country.json`, `<region>.json` |
| `ems/` | the energy management system: fixed yearly cost, hardware bought once with the battery, fees on the ancillary revenue and on the bill saving (`ems.py`) | `ems/default.json` |

The market (country, region, utility, tariff year) is chosen once for the run and sets its currency; its tariff
files belong to the grid block (`elements/grid/params/tariffs`).

In the case file: `"general": {"commercial": {"business_model": "eaas"}}` (default direct sales). The other values are
changed with the run's `overrides`, in the reference layout; each goes to the item that owns it (e.g. `capex`,
`finance` and `ancillary.rate_per_kw_year` to commercial, `subsidies` to subsidies, `ems` to EMS,
`ancillary.reserve` to the battery block).

Where a block and a general item meet (the battery's net price = commercial gross price after the subsidy; its
investment = net price + EMS hardware; its ancillary revenue = reserved kW from the battery x rate from commercial),
the `System` in `system/setup.py` joins them.
