# Greenhouse energy model: blocks, parameters and optimisation

A brief of the model for preparing a presentation. It describes what the model is for, every block with its inputs
and parameters, and the optimisation in plain terms. The full formulas are in `OPTIMISATION.md`; the scope of the
thesis is in `thesis.md`.

**Before building slides:**
- The audience and the key message of the presentation are not set in this file: [TO CHECK with Charbel].
- Many parameter values are placeholders, marked TO CHECK below. Present them as placeholders, not as data.
- The example input data is synthetic (made from formulas), so example results are illustrations, not findings.

## 1. What the model is for

EPFL master thesis with Voltiris: *A Path to Greenhouse Self-Sufficiency: Heat and CO2*. The model helps a grower see
which technologies to install, and how large, to lower the yearly cost of running a greenhouse. It covers its
electricity, heat and CO2.

The model represents the greenhouse and its energy system as **blocks** (one per technology), puts them together,
and optimises how they run over a whole year and how big they should be. It then shows, for each technology,
what the site gains or loses with it against without it.

Countries and tariffs available: Switzerland (Geneva, SIG 2026), the Netherlands (Westland Infra, MS 2026) and France
(TURPE 7, HTA 2025).

## 2. The system at a glance

- **Carriers:** electricity, heat, CO2, gas.
- **Time:** one year in steps of 15 minutes (35,040 steps). Hourly or daily input curves (any regular step of whole
  quarter hours) are converted automatically; a monthly curve is not.
- **Foresight:** the optimisation knows the whole year's prices and demand in advance (perfect foresight). The results
  are therefore the best a system could do; a real controller does somewhat worse.
- **Money:** every value is in the market's currency (CHF or EUR), converted with one exchange rate (1 CHF = 1.09 EUR).
- **Interface:** a browser page where the user picks a scenario or builds a system by clicking blocks on a drawing of
  the greenhouse, gives each block its data, runs, and reads the results.

### Links between blocks

| Rule | Example |
|---|---|
| Always in the system | greenhouse demand, grid |
| Comes with another block | the gas supply comes and goes with the gas boiler |
| Needs a source | a heat storage needs a heat source (the gas boiler or the heat pump) |
| The only source of a demand is not evaluated "without" | the gas boiler while it is the only heat or CO2 source; the heat pump while it is the only heat source; the external CO2 while it is the only CO2 source |

## 3. The blocks

Status: **built** = runs today; **planned** = in the thesis, not built yet. "Sized" = the model chooses its size.

| Block | Role | Status | Sized |
|---|---|---|---|
| Greenhouse demand | electricity load, heat demand, CO2 demand | built | no |
| Voltiris | Voltiris PV modules on the greenhouse | built | no (module count given) |
| Existing PV | PV already on site | built | no |
| Grid | import, export, tariffs, capacity charges | built | no |
| Battery | stores electricity | built | yes, kWh |
| Gas supply | natural gas bought from the network | built | no |
| Gas boiler | gas to heat and flue gas CO2 | built | yes, kW of heat |
| Heat pump | electricity and outside air to heat | built | yes, kW of heat (or a fixed size) |
| Heat storage | hot water tank, shifts heat in time | built | yes, kWh of heat |
| External CO2 | liquid CO2 bought | built | no |
| CHP, data center, SOFC, electric backup heater | other thesis technologies | planned | |

### 3.1 Greenhouse demand

- **Data (one file):**
  - electricity load (kW), always;
  - heat demand (kW) and CO2 demand (kg/h), when a block supplies them.
- **Setting:** CO2 demand "must be met" (the boiler may run only for CO2) or "by-product" (the greenhouse takes the
  boiler's CO2 only while it heats). With external CO2, the demand is always met.
- **Parameters:**

| Parameter | Default | Note |
|---|---|---|
| Penalty for unmet heat | 10 per kWh | solver device, not a price |
| Penalty for unmet CO2 | 10 per kg | solver device, not a price |

### 3.2 Voltiris

- **Data:** the yield of one module (W per module).
- **Setting:** number of modules.

| Parameter | Default | Note |
|---|---|---|
| Module power | 146 Wp | the yield file says 145 Wp, to confirm |

- **Business model** (Commercial page): direct sales (the grower buys the modules) or energy as a service (Voltiris
  owns them, the grower pays 180 CHF per MWh of Voltiris energy used on site).
- **Price:** 1.80 CHF per Wp, life 25 years. Subsidy on the modules: none in Geneva and the Netherlands, 50 % in France
  (to confirm).

### 3.3 Existing PV

- **Data:** its output (kW).
- No parameters; its cost is sunk. It shares the site's meter with Voltiris.

### 3.4 Grid

- **Data:** the day-ahead price, for tariffs based on it (NL, FR).
- **Settings:** import and export limits (automatic: twice the highest load, with a heat pump its draw for the whole
  heat demand included; 1.1 × the highest PV); the tariff regime.
- **Parameters (tariff files per country, region and utility):**
  - energy and network prices per period;
  - capacity charges: monthly peak (with or without an annual ratchet), yearly peak, or the French TURPE staircase;
  - the export price;
  - regimes. In Geneva, SIG has two regimes chosen by the yearly hours of use (DUP): regime A at or below 3,000 h,
    regime B above.
  - SIG export price used: 0.05 CHF/kWh (the tariff document's value for PV is unconfirmed).

### 3.5 Battery

Values from the reference battery model (Jesse's model, which the blocks reproduce exactly).

| Parameter | Default |
|---|---|
| C-rate (kW per kWh bought) | 0.5 |
| Charge and discharge efficiency | 97 % each |
| State of charge window | 10 % to 90 % |
| Self-discharge | 0.1 % per day |
| Reserve kept for grid services | 25 % of the window and of the power (CH, NL, FR) |
| Price | 400 CHF per kWh, all sizes |
| Life | 10 years |
| Replacements (payback table only) | 60 % of the price, 1.5 times over the 25-year PV life (25 / 10 - 1) |
| Ancillary revenue | 90 CHF per reserved kW and year (CH); 98.1 EUR (FR, NL) |
| Subsidy (Geneva) | 75 % up to the OCAN maximum size: yearly load ÷ 365 × 0.6 |
| Subsidy (France, Netherlands) | 50 % (to confirm); none |
| EMS | 2,500 CHF per year, 1,000 EUR hardware, fees 0 % |

**Sizing settings:** objective (highest lifetime profit, shortest payback, or a custom size), the sizes to test, a
fine grid, and a cap at the subsidised maximum.

### 3.6 Gas supply

- **Data:** the gas price (EUR per kWh), at any regular step (for example daily); or a fixed price.

| Parameter | Default | Note |
|---|---|---|
| Emission factor | 0.202 kg CO2 per kWh of gas | IPCC 2006 default, to check against the national value |
| Carbon levy | 0 per kg CO2 | TO CHECK: placeholder |
| Fixed price | none | used only without a file |

### 3.7 Gas boiler

| Parameter | Default | Note |
|---|---|---|
| Efficiency | 90 % | TO CHECK: placeholder |
| Share of flue gas CO2 usable | 100 % | TO CHECK: placeholder |
| Price | 100 EUR per kW of heat | TO CHECK: placeholder |
| Fixed O&M | 2 EUR per kW and year | TO CHECK: placeholder |
| Variable O&M | 1 EUR per MWh of heat | TO CHECK: placeholder |
| Life | 20 years | TO CHECK: placeholder |

**Sizing settings:** objective (lowest lifetime cost, smallest that covers the demand, or custom) and the sizes to
test (automatic: around the heat the demand needs at its busiest step).

### 3.8 Heat pump

- **What it does:** turns electricity into heat, taking heat from the outside air (scenario S2; the data center as a
  warmer source comes later). At every quarter hour the model takes the heat from whichever source is cheaper: the
  heat pump's electricity divided by its COP, or the boiler's gas divided by its efficiency. When the boiler must run
  for the CO2 demand, its heat comes with the CO2 and the heat pump runs less.
- **COP:** from the outside temperature, COP = nominal COP x (60 - reference temperature) / (60 - outside
  temperature), so it falls when it is cold; or constant. With the example temperatures (-3 to 23 °C) it is 2.5 to
  4.3.
- **Its electricity** is part of the site's load: it shows on the Electricity tab and in the grid bill.

| Parameter | Default | Note |
|---|---|---|
| Supply temperature | 60 °C | the greenhouse's heating water |
| COP mode | dynamic (from the outside temperature) | or constant |
| Nominal COP | 3.0 at 7 °C outside | TO CHECK: placeholder |
| Price | 800 EUR per kW of heat | TO CHECK: placeholder |
| Fixed O&M | 10 EUR per kW and year | TO CHECK: placeholder |
| Life | 20 years | TO CHECK: placeholder |

**Input file:** the outside temperature (the same file as the heat storage's dynamic loss can be used).
**Size:** chosen by the model together with the other sized blocks, or fixed by the user.

### 3.9 Heat storage

- **Data:** the outside temperature, only for the dynamic heat loss.

| Parameter | Default | Note |
|---|---|---|
| Charge and discharge efficiency | 95 % each | TO CHECK: placeholder |
| Power | 0.25 kW per kWh (full in 4 hours) | TO CHECK: placeholder |
| Heat loss, constant | 0.5 % of the heat stored per hour | TO CHECK: placeholder |
| Heat loss, seasonal | winter 0.6, spring 0.5, summer 0.4, autumn 0.5 % per hour | TO CHECK: placeholders |
| Heat loss, dynamic | 0.5 %/h at 10 °C outside, tank at 70 °C, scaled by the temperature difference | TO CHECK: placeholders |
| Price | 30 EUR per kWh | TO CHECK: placeholder |
| Fixed O&M | 0.3 EUR per kWh and year | TO CHECK: placeholder |
| Life | 25 years | TO CHECK: placeholder |

### 3.10 External CO2

- **Data:** the CO2 price (EUR per kg), at any regular step (for example a daily curve over the year); or a fixed
  price.

| Parameter | Default | Note |
|---|---|---|
| Fixed price | none | used only without a file |
| Fixed cost per year (tank, evaporator) | 0 | TO CHECK: placeholder |
| Most CO2 per hour | none (as needed) | TO CHECK |

- **What it changes:** at every quarter hour the model chooses between buying CO2 and burning gas in the boiler for
  its flue gas CO2, whichever costs less. Bought CO2 is not counted in the site's emissions.

### 3.11 General items (not tied to one block)

| Item | Holds |
|---|---|
| Market | country, region, utility, year; sets the currency and the tariff |
| Commercial | Voltiris business model, investment prices, lifetimes, the ancillary revenue rate |
| Subsidies | on the Voltiris modules and on the battery, per country and region |
| EMS | the energy management system's yearly cost, hardware and fees |

## 4. The optimisation in plain terms

**What it decides:**
1. how every unit runs at every quarter hour: buying or selling electricity, charging or discharging the battery,
   burning gas, running the heat pump, storing heat, buying CO2;
2. the size of the sized blocks: battery (kWh), gas boiler (kW), heat pump (kW), heat storage (kWh).

**What it minimises:** the site's yearly cost:

- **running cost:** the grid bill (energy, network, capacity charges, minus export revenue, plus the EaaS fee), gas,
  carbon levy, bought CO2 and the CO2 supply's fixed cost, operation and maintenance, the battery's EMS costs (checked
  after the optimisation), minus the battery's ancillary revenue;
- **investment per year:** each investment divided by its life (no discounting).

**What it must respect (at every quarter hour):**
- **Electricity balance:** PV + grid import + battery discharge = load + heat pump + grid export + battery charge.
- **Heat balance:** boiler heat + heat pump heat + heat from the tank = heat demand + heat into the tank + heat
  released.
- **CO2 balance:** boiler flue gas CO2 + bought CO2 = CO2 demand + CO2 vented.
- **Capacities:** nothing runs above its size; the battery and the heat tank stay within their energy limits and lose
  a little energy over time; the grid connection has limits.
- **Tariff and grid rules:** capacity charges on the peaks; the Geneva regime set by the hours of use; one meter
  (no import and export at the same moment where that could be gamed); battery exports limited to PV energy where the
  contract requires it.

**How sizes are chosen:** all sizes are chosen together in the same optimisation, so the model sees that a heat
storage lets the boiler be smaller. A size given in the case stays fixed. The results show the technical side first:
each size, how hard it works over the year (full-load hours, hours at full size), what one more unit would cost per
year, the year's energy flows; then the money.

**With and without each technology:** for every technology the system could do without, the model sizes the system
without it again and shows what the technology brings: its effect on grid import, gas, CO2 emitted and
self-sufficiency, then on the yearly cost line by line, the investment and its payback.

**How much the sizes matter:** each size -10 % and +10 %, only the year's operation solved again, everything else at
its size. **Battery check:** the battery sized again by the reference battery model's sweep and set against its joint
size; it can be switched off.

**Method:** linear programming (PyPSA with the HiGHS solver). A normal year solves in about 25 seconds; the joint
sizing in about 2 minutes.

## 5. What the results show

| Tab | Content |
|---|---|
| System | the site's yearly cost (running and investment per year), the sizes, every technology with and without it |
| Electricity | Voltiris and existing PV with and without them, what the PV saves, how the load is covered, where the PV goes, self-consumption and self-sufficiency, money to and from the grid |
| Battery | yearly value, payback, sizes tested, bills, month by month |
| Gas boiler | lifetime cost of each size, heat and CO2 per day |
| Heat pump | size, heat given, electricity drawn, seasonal COP, cost per MWh of heat against the boiler's, heat by source per month, COP against the outside temperature, one week hourly |
| Heat storage | where its value comes from, gas saved, how it shifts heat over a week |
| CO2 | CO2 from the flue gas against bought CO2, per month and per day, with the prices |

## 6. Illustrations from the synthetic examples

These come from synthetic data with placeholder prices. They show what the model can tell, not real results.

- **Sizing together:** sized alone, the gas boiler comes out at 1,350 kW, the heat demand's peak. Sized together with
  a heat storage, the model chooses a 1,237 kW boiler and a 551 kWh tank. The tank is then worth 745 CHF per year to
  the site. Earlier, sized one at a time with the boiler fixed first, no tank size paid back within the tank's life
  (the best took 54 years): the tank's value is in the smaller boiler.
- **Battery (Geneva, 500 Voltiris modules):** sized together, 2,495 kWh, the same size as the reference battery
  model's sweep (both at the subsidised maximum). Each size -10 % or +10 % raises the yearly cost (by 1,519 and
  1,475 CHF). The site with this battery costs 23,450 CHF per year less than
  without it, with the battery and its replacements spread over the PV life (the replacements are not subsidised).
  The first purchase of 250,417 CHF, after subsidy, pays back in 3.6 years.
- **Buying CO2 or burning gas:** with a CO2 price that is cheaper in summer, the model buys 22.7 t of CO2 in summer
  instead of running the boiler only for CO2. It keeps using the boiler's flue gas in winter, when the heat is needed
  anyway. Compared with the same site without external CO2, this lowers the yearly cost by 1,250 CHF and the CO2
  emitted by 22.7 t.
- **Heat pump next to the boiler:** with the example prices (gas about 0.032 CHF/kWh, grid about 0.16 CHF/kWh) the
  heat pump's heat costs more than the boiler's at almost every hour, and the boiler runs for CO2 anyway, so the
  model gives it no size. With a carbon levy of 0.12 CHF per kg of CO2 (a test value, not a sourced one), the model
  chooses a 472 kW heat pump next to a 1,013 kW boiler (instead of 1,350 kW alone): it gives 42 % of the heat at a
  seasonal COP of 2.9 and lowers the yearly cost by 10,255 CHF.

## 7. Limits to state

- Perfect foresight: an upper bound on what a real controller reaches.
- Investments are spread over their lives without discounting (to check).
- The heat pump links heat and electricity; the CHP and the electric backup heater are not built yet. The heat pump's
  size holds at any outside temperature and it has no minimum load; its source is the outside air only.
- No minimum load or start-up cost for the boiler.
- The heat and CO2 demand are inputs; the greenhouse climate is not modelled, and the effect of the Voltiris modules
  on the demand is ignored.
- Several parameters are placeholders (TO CHECK above), and the example data is synthetic.

## 8. A possible slide outline

1. The question: which technologies lower a greenhouse's yearly cost (electricity, heat, CO2).
2. The approach: blocks on one site, one year at 15 minutes, optimised for the lowest yearly cost.
3. The blocks: what exists today and what is planned (table of section 3).
4. Inputs and parameters: data curves per block; sourced values and placeholders.
5. The optimisation: what it decides, what it minimises, the balances (section 4).
6. Sizing together: what each size is, how hard it works, how much it matters (+/- 10 %).
7. With and without each technology: what it brings, line by line.
8. Illustrations from the synthetic examples (clearly labelled).
9. Limits and next steps: real data, CHP and heat pump, comparing scenarios, discounting.
