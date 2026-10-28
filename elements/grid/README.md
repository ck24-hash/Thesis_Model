# grid: connection, tariffs, markets

**Market.** A market is a tariff file `params/tariffs/<country>/<region>/<utility>_<year>.json`, merged over
`<country>/_country.json` and `<region>/_canton.json` or `_region.json` (the more specific file wins). It sets the
currency of the whole run.

| Market | `market` in a case file |
|---|---|
| CH, SIG (Geneva) | `{"country": "CH", "region": "GE", "utility": "SIG", "year": 2026}` |
| NL, Westland Infra MS | `{"country": "NL", "region": "WestlandInfra", "utility": "MS", "year": 2026}` |
| FR, TURPE 7 HTA, reference supplier | `{"country": "FR", "region": "HTA", "utility": "Reference", "year": 2025}` |

**Tariff** (`tariffs.py`, the reference model's code unchanged): import price as a sum of components (flat, peak and
off-peak, season, TURPE slot, day-ahead), capacity charges (monthly peak with or without the annual ratchet, yearly
peak, TURPE staircase), export price (fixed or day-ahead), regimes (SIG A/B by DUP, TURPE LU/CU). The day-ahead
column (`Day ahead kWh`, EUR/kWh, role `day_ahead_eur_kwh`) is needed where the tariff uses it (NL, FR).

**Network** (`block.py`): generators `grid_import` (at the regime's price) and `grid_export` (at the export value the
system gives: the feed-in, or the EaaS value), with limits from the case or automatic (2 x highest load, 1.1 x highest
PV). The capacity charges are added to the objective, and the DUP lock can hold the year's DUP in one regime.

**Contract rule.** `battery_export` in the tariff file: `any` (CH, NL) or `pv_only` (FR: energy bought at a fixed
price may not be resold). The system applies it to the battery (`system/dispatch.py`).
