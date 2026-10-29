# gas_supply: natural gas from the network (the fuel block)

**Network** (`block.py`): the bus `gas` and a `Generator` named `gas_supply` on it. Its marginal cost at step t is
what 1 kWh of gas costs (lower heating value):

    cost_t = price_t + levy x ef            (per kWh of gas; levy per kg CO2, ef in kg CO2 per kWh of gas)

Its capacity is what the gas users can burn (today the boiler's S / eta), so it never limits them. Every block that
burns gas takes it from the bus `gas` (today the gas boiler; the CHP later).

**Input file** (its own): the gas price, column `Gas price (EUR/kWh)` (role `gas_price_eur_kwh`), EUR per kWh of gas.
Any step: a daily or hourly file is repeated in each quarter hour (prices are repeated). The price is converted to the
market's currency like the day-ahead price. Without a file, the fixed price `gas.price_per_kwh` is used.

**Parameters** (`params/gas/default.json`):

| Key | Default | What it is |
|---|---|---|
| `emission_factor_kg_per_kwh` | 0.202 | kg CO2 per kWh of gas burnt: IPCC 2006 default for natural gas, 56.1 t CO2/TJ. TO CHECK against the national inventory value |
| `co2_levy_per_kg` | 0 | carbon levy per kg CO2, market currency. TO CHECK: placeholder (CH has a levy on heating fuels, with exemptions to check for greenhouses; FR and NL to check) |
| `price_per_kwh` | none | fixed gas price per kWh, market currency, used only when the block has no input file |

The emission factor sets both the CO2 the boiler can give the greenhouse and the CO2 emitted (A17).
