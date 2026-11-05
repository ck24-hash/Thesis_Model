# external_co2: bought liquid CO2

**Network** (`block.py`): a `Generator` named `co2_bought` on the bus `co2`, at the CO2 price per kg at each step,
able to deliver the most CO2 per hour of the supply (else the demand's peak). It sits next to the gas boiler's flue
gas on the same bus, so at each step the optimisation buys CO2 or burns gas for it, whichever costs less:

    CO2 bus:   boiler flue gas CO2 + CO2 bought + unmet = CO2 demand + CO2 vented

Burning gas only for CO2 costs about (gas price + levy x emission factor + boiler variable O&M x efficiency) /
(emission factor x usable share) per kg; when the greenhouse needs the heat, the flue gas CO2 comes free. With
external CO2 the CO2 demand must be met (the greenhouse's by-product mode does not apply), and it works without a
boiler too (all the CO2 is then bought). It is not sized; with it, the boiler study's needed size counts the heat
demand only.

**Input file** (its own): the CO2 price, column `CO2 price (EUR/kg)` (role `co2_price_eur_kg`), EUR per kg, any
regular step (an hourly or daily curve over the year; prices are repeated in each quarter hour; a monthly curve is
not converted: give it per day), converted to the market's
currency. Without a file, the fixed price is used.

**Parameters** (`params/external_co2/default.json`):

| Key | Default | What it is |
|---|---|---|
| `price_per_kg` | none | fixed CO2 price per kg (market currency), used only without an input file |
| `fixed_cost_per_year` | 0 | yearly fixed cost of the supply (tank, evaporator rental, contract). TO CHECK: placeholder |
| `max_kg_h` | none | the most CO2 per hour the supply delivers; none = as much as needed. TO CHECK |

In the site's yearly cost: "CO2 bought" (and the fixed cost when set); in the quantities: "CO2 bought (t)". Bought CO2
is not counted in the site's emissions (thesis.md A21). Results: the CO2 tab (its with and without, `system/effects.py`;
flue gas against bought CO2, with the prices; with a boiler, what buying saves against burning gas only for the CO2).
