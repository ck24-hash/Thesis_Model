# ng_boiler: natural gas boiler

**Network** (`block.py`): a PyPSA `Link` named `boiler`, from the bus `gas` to the bus `heat`, with a second output
to the bus `co2`. It needs the gas supply block (`elements/gas_supply`). For a size S in kW of heat, at each step t:

    heat_t = eta x gas_t <= S                     (kW; the link's p_nom is S / eta kW of gas)
    co2_t  = ef x f_use x gas_t                   (kg/h to the bus co2; ef from the gas supply)
    cost_t = gas_t x (price_t + levy x ef) + var_om x heat_t

The gas price and levy are on the gas supply's generator; the variable O&M is the link's marginal cost
(var_om x eta per kWh of gas). The boiler can modulate from 0 to S at no cost (no minimum load or start-up yet,
thesis.md section 6).

**Parameters** (`params/boiler/default.json`):

| Key | Default | What it is |
|---|---|---|
| `efficiency` | 0.9 | kWh of heat per kWh of gas, lower heating value. TO CHECK: placeholder |
| `co2_use_frac` | 1.0 | share of the flue gas CO2 that can go to the greenhouse after cleaning; the rest is vented. TO CHECK: placeholder |

Its money is in `general/commercial`: `capex.boiler_per_kw_th` (100 EUR per kW of heat),
`capex.boiler_fixed_om_per_kw_year` (2 EUR), `capex.boiler_var_om_per_mwh_heat` (1 EUR), `finance.boiler_life_yr`
(20 years). All TO CHECK: placeholders.

**Size** (`system/joint.py`, `system/README.md`): always from the joint sizing, one optimisation with the other sized
blocks for the site's lowest yearly cost, unless the case fixes it (`blocks.ng_boiler.sizing`: `{"objective":
"custom", "custom_kw": X}`, 0 = no boiler). When its size is free the heat demand, and the CO2 demand, must be met.

**Study** (`sizing.py`, `study.py`): the boiler's year at its size, run after the joint sizing (none at size 0).

1. The size the demand needs, for comparison: the largest heat at one step, or, when the CO2 demand must be met and
   no CO2 can be bought (no external CO2), the heat that comes with the gas burnt for the CO2 (CO2 demand / (ef x
   f_use / eta)), whichever is larger (`needed_kw`).
2. The year optimised at that size (`evaluate_size`; the electricity side runs too, without battery): heat, unmet
   heat and CO2, gas, gas cost, levy, O&M, CO2 bought (with external CO2), yearly cost, investment, lifetime cost =
   investment + yearly cost x boiler life. The size covers the demand when it leaves nothing unmet (at most 1e-6 of
   the year's demand).
3. Written: summary, monthly table, dispatch.

**Assumptions** (thesis.md section 5): A4 (the boiler may run for CO2 alone, its heat then released; the greenhouse's
`co2_mode`), A15 (unmet demand is a penalised slack), A16 (always sized together with the other sized blocks), A17
(all the CO2 of the gas burnt counts as emitted). A8 (boiler CAPEX sunk in reference cases) is not applied yet: the
study prices a new boiler.

**With and without** (`system/effects.py`, at the top of its results tab): not evaluated when the boiler is the only
heat source or the only CO2 source, since the system without it would leave that demand without a source.
