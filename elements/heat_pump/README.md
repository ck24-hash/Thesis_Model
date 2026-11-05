# heat_pump: heat pump (air source for now)

**Network** (`block.py`): a PyPSA `Link` named `heat_pump` from the electricity bus `main` to the heat bus `heat`,
with the COP of each step as its efficiency. Without a data center (not built yet) its heat source is the outside
air (scenario S2). It sits next to the gas boiler (when there is one) on the heat bus, so at each step the
optimisation takes heat from whichever is cheaper: the heat pump's electricity (at the step's import price with its
capacity charges, or PV) divided by the COP, or the boiler's gas divided by its efficiency. When the boiler runs
anyway for the CO2 demand, its heat comes with it, and the heat pump is used less. For a size Q in kW of heat, at each step t:

    heat_t = COP_t x electricity_t
    electricity_t <= Q / COP_t          (so heat_t <= Q at any outside temperature)

The link's limit is on the electricity side: `p_nom = Q / COP_min` (the lowest COP of the year) with
`p_max_pu_t = COP_min / COP_t`. Heat it gives beyond the demand is released or goes into the heat storage. Its
electricity is part of the site's load (bills, self-consumption, self-sufficiency; thesis.md A23). It gives no CO2:
without the gas boiler or external CO2, the greenhouse's CO2 demand is not part of the run.

**COP** (`cop.mode`):

| Mode | COP at step t |
|---|---|
| `dynamic` (default) | `nominal x (supply_temp_c - ref_outside_temp_c) / (supply_temp_c - T_out,t)`, with the outside temperature of the block's input file |
| `constant` | `nominal` all year |

The dynamic COP is a constant share of the Carnot COP between the outside air and the supply temperature
(thesis.md 3.4: `COP = eta_carnot x T_sup / (T_sup - T_src)`, temperatures in K), with
`eta_carnot = nominal x (T_sup - T_ref) / T_sup`: 3.0 at 7 °C outside and 60 °C supply is `eta_carnot` = 0.48. It falls
as the outside air gets colder. With the example temperature file (-3 to 23 °C) it is 2.52 to 4.30.

**Input file** (its own, only for the dynamic COP): the outside temperature, column `Outside temperature (C)` (role
`hp_outside_temp_c`), °C, any step (an hourly file is repeated in each quarter hour). The heat storage's dynamic loss
reads the same column, so both can use the same file.

**Parameters** (`params/heat_pump/default.json`):

| Key | Default | What it is |
|---|---|---|
| `supply_temp_c` | 60 | temperature of the heat given to the greenhouse (its heating water), °C |
| `cop.mode` | dynamic | `dynamic` or `constant` |
| `cop.nominal` | 3.0 | the COP at the reference outside temperature and the supply temperature (constant mode: all year). TO CHECK: placeholder |
| `cop.ref_outside_temp_c` | 7 | the outside temperature at which the COP is the nominal COP. TO CHECK: placeholder |

Its money is in `general/commercial`: `capex.heat_pump_per_kw_th` (800 EUR per kW of heat),
`capex.heat_pump_fixed_om_per_kw_year` (10 EUR), `finance.heat_pump_life_yr` (20 years). All TO CHECK placeholders.

**Size**: in the case, `blocks.heat_pump.sizing`: `{"objective": "joint"}` (default) = sized in the joint sizing
(`system/joint.py`) with the other sized blocks, for the site's lowest yearly cost; `{"objective": "custom",
"custom_kw": 500}` = fixed at that size (0 = no heat pump). Every sized block is always sized together (thesis.md
A16, A24).

**Results** (`study.py`, from the site's year at the sizes chosen): its size, the COP over the year, the SPF (heat
given / electricity drawn over the year), the heat it gives against the demand and the boiler, its electricity per
month (also part of the site's load on the Electricity tab), its electricity at the import price, its investment and
O&M, and its cost per MWh of heat next to the boiler's running cost per MWh of heat. What it brings to the site is
its "with and without" (`system/effects.py`), not evaluated when it is the only heat source.

**Not modelled yet** (thesis.md A22): a minimum part load (it would need integer variables), a capacity that falls
when the outside air is cold (the size holds at any temperature), a different supply temperature for charging the
heat storage, and the data center as a warmer source (S3, S4).
