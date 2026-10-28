# Battery model (PV + battery sizing)

Jesse's PV + battery techno-economic model (the notebook `CH_fixed_battery_5.0_+PV_SIG`), split into one core engine
and parameter blocks with a map per country. The backbone is the CH (SIG) model; only what is country specific changes
per country: the tariff (import price, capacity charges, export price), subsidies, the ancillary rate and the
currency. Switzerland (SIG, Geneva), the Netherlands (Westland Infra, day-ahead contract) and France (TURPE 7 HTA)
are in. Not wired into the site yet: see "For Paul" below.

## Run a study

```bash
pip install -r elements/battery_reference/requirements.txt
python elements/battery_reference/run_case.py "C:/.../<site folder>/case_2026.json"
```

A study is one case file. It holds only what is specific to the study (the input workbook, the market, the module
count, the grid limits) and stays next to the grower's data on SharePoint, never in this repo.
`case_template.json` is a blank one; every key is described at the top of `run_case.py`. The results go next to
the case file: `summary_<tag>.json` and `results_<tag>.xlsx` (summary, sizing sweep, payback table, yearly bills by
component, monthly tables, dispatch).

The markets:

| Market | `market` in the case file |
|---|---|
| CH, SIG (Geneva) | `{"country": "CH", "region": "GE", "utility": "SIG", "year": 2026}` |
| NL, Westland Infra MS | `{"country": "NL", "region": "WestlandInfra", "utility": "MS", "year": 2026}` |
| FR, HTA, reference supplier | `{"country": "FR", "region": "HTA", "utility": "Reference", "year": 2025}` |

Every country uses the CH input workbook format ("+PV" files): `Loadcurve (kW)`, `Production voltiron (W)` per
module, `Current PV feed-in (kW)`, `Day ahead kWh` (EUR/kWh), `Month`, `Day`, `Hour`, `Minute`. NL and FR need the
day-ahead column at every step (import and/or export are priced on it).

To change one value for one study, use `overrides` in the case file, in the market's currency, for example
`"overrides": {"tariff": {"export": {"per_kwh": 0.066}}}` or a French site's own off-peak hours
`{"tariff": {"calendar": {"peak_hours": {...}}}}`. To change it for every study, edit the parameter file.

## Run time

Measured on Jesse's laptop (Ryzen 5 PRO 8540U), one full year in 15-minute steps, nothing else running:

| | One battery size | One study (15 sizes) |
|---|---|---|
| CH (SIG) | about 35 to 45 s, up to 3 solves where a size crosses the A/B regime | about 10 to 14 min |
| NL | about 45 s | about 11 to 12 min |
| FR with the PV-only export rule | about 80 s | about 20 min |

Sizes are solved one after the other; solving them in parallel (the laptop has 6 cores) is not done yet.

## What is the same everywhere (the CH backbone)

- **The engine**: one PyPSA LP per battery size (HiGHS), perfect foresight, PV must run (no curtailment), the
  no-battery case solved by the same model, a hard grid import and export limit (`grid` in the case file).
- **One meter**: a site imports or exports, and a battery charges or discharges, never both at the same moment;
  within a quarter hour they may switch (time sharing). Where the tariff makes cheating pay (export worth more than
  import, as for much of a French year against a fixed contract price; or a negative price, as at times in NL), the
  exact limits on the quarter hour's averages hold, with shortfall D = (load - PV)+, surplus S = (PV - load)+,
  battery power P and discharge efficiency eta:
  import <= D + max(1 - S/P, 0) x charging, export <= S + max(eta - D/P, 0) x discharging,
  charging + discharging <= P. So nothing goes from the grid straight back to the grid. These are linear, so the
  model stays an LP. CH never meets either case, so it is unchanged.
  Exact on/off switches (binary variables) were tried and dropped: on a French year they need about 15,000 switches
  and take over 20 minutes per battery size, for a result within 0.02% of the rule above. Under EaaS the import and
  export rule is the CH model's fixed bounds (export only the PV surplus, no import during one, so the battery does
  not export); the battery rule still applies at negative prices.
- **Tech** (`params/tech/default.json`): 0.5C, 97% / 97%, SoC 10-90%, 0.1%/day self-discharge, 146 Wp modules.
- **Capex** (`params/capex/default.json`), the same real price converted at 1 CHF = 1.09 EUR (`params/fx.json`):
  battery 400 CHF/kWh = 436 EUR/kWh, PV 1.80 CHF/Wp = 1.962 EUR/Wp. Replacements over the 25-year PV life: the
  battery is bought once in full, then 1.5 more battery lives (10 years each) at 60% of the gross price, unsubsidised.
- **Finance** (`params/finance/default.json`): battery 10 years, PV 25 years.
- **EMS** (`params/ems/default.json`), same real price everywhere:

  | | CH | NL, FR |
  |---|---|---|
  | Fixed yearly cost | 2,500 CHF | 2,725 EUR |
  | EMS capex (bought once, no subsidy, not replaced) | 917 CHF | 1,000 EUR |
  | Fee on ancillary revenue, Voltiris / external | 0% / 0% | 0% / 0% |
  | Fee on the bill saving vs no battery, Voltiris / external | 0% / 0% | 0% / 0% |

  The bill saving is energy + peak savings (not ancillary, which has its own fee), and the fee applies only when it
  is positive. Fees and the fixed cost come off the battery's yearly value in the sizing and the payback; the capex is
  added to the battery investment.
- **Sizing**: 100 to 1,500 kWh in steps of 100, no fine stage; the choice by lifetime profit (among sizes that pay
  back within the battery life), payback, or a custom size. With a threshold subsidy (CH's OCAN rule) the sweep stops
  at the subsidised maximum.
- **Business models**: direct sales and EaaS (180 CHF/MWh = 196.2 EUR/MWh of Voltiris energy used on site) in every
  country.

## What differs per country

| | CH (SIG, Geneva) | NL (Westland Infra MS) | FR (TURPE 7 HTA) |
|---|---|---|---|
| Import price | energy per season x HP/HD + network per regime x 1.132 cantonal levy + federal 0.0276 CHF/kWh | day-ahead + energy tax 37.35 + transport 24.20 EUR/MWh | supplier energy per season x HP/HD + TURPE energy per slot + capacity GC 8.77 (winter HP) + accise 30.85 EUR/MWh |
| Calendar | HP weekday 07-22, weekend 17-22; winter Oct-Mar | none | HP Mon-Sat 06-22, Sunday off-peak; pointe Dec-Feb Mon-Sat 08-10 and 17-19; winter Nov-Mar |
| Capacity charges | monthly HP peak, annual ratchet, 6.40 / 10.75 CHF/kW/month x 1.132 | year peak 24.48 EUR/kW/yr + each month's peak 3.09 EUR/kW/month, all hours | TURPE CS staircase: pointe 35.33, HPH 32.30, HCH 20.39, HPB 14.33, HCB 11.56 EUR/kW/yr (LU) |
| Regimes | A / B by DUP (3,000 h) | one | LU (default) / CU, chosen in the case |
| Export | 0.05 CHF/kWh fixed | day-ahead | day-ahead |
| Subsidies | battery 75% up to the OCAN size | none | battery 50%, PV 50% (from the FR notebook; to confirm) |
| Ancillary | 90 CHF/kW/yr on 25% of the battery | 98.1 EUR/kW/yr on 25% | 98.1 EUR/kW/yr on 25% |
| Battery export | anything | anything | only PV energy (`pv_only`) |

The French calendar and TURPE rates follow CRE deliberation 2025-78 (TURPE 7 HTA-BT, in force 1 August 2025): the
pointe is December to February, Monday to Saturday, 2 hours within 08-12 and 2 hours within 17-21; Sunday is all
off-peak; the grid operator sets the exact hours, and CRE is moving off-peak hours towards summer afternoons by
2027, so a site's own hours belong in its case file. The FR notebook's TURPE energy rates (48.40 / 28.30 / 8.20 /
5.40 EUR/MWh) were not TURPE 7; the official LU rates (26.5 / 21.0 / 14.7 / 9.2 / 6.8) are used.

**Battery export rule (FR on, CH and NL off).** The French fixed supply price (85 to 170 EUR/MWh) is below the
day-ahead export price in a large part of the year (44% of the quarter hours on a 2026 test curve). Left free, the
model then uses the battery to buy at the contract price and sell at day-ahead: on a test year the battery's value grew
in a straight line with its size and the site imported more than it used. A fixed-price contract may not be resold, so
the FR supplier file sets `"battery_export": "pv_only"`: the battery keeps an account of the energy it bought from the
grid (sharing the battery's capacity and power, with its standing loss), that energy may only serve the site (peak
shaving), and only PV energy, stored or not, may be exported. A site whose contract allows trading sets
`"battery_export": "any"` in its case (`"overrides": {"tariff": {"battery_export": "any"}}`). CH and NL do not need the
rule (CH sells at 0.05 CHF/kWh, below every purchase price; NL always buys at day-ahead + 6.2 ct), so it is off there
and CH is unchanged.

## Layout

```
engine/              the same for every country
  inputs.py          the input workbook -> load, Voltiris PV, existing PV, day-ahead per 15 minutes
  setup.py           one study's series, blocks, masks and prices in one object
  dispatch.py        the PyPSA LP: PV, load, grid, battery; capacity charges; DUP lock; one-meter switches
  sizing.py          the size sweep and the choice by profit, payback or custom size
  flows.py           SC and SS, the yearly bill, the monthly table, the self-consumption / arbitrage split
  pipeline.py        one study from start to end, in the notebook's order
blocks/              the functions that use the parameters
  tariffs.py  tech.py  capex.py  subsidies.py  ems.py  business_model.py  finance.py
params/              the numbers
  fx.json                              1 CHF = 1.09 EUR, for the shared money values
  tariffs/<country>/_country.json      currency, national levies, export basis
  tariffs/<country>/<region>/_canton.json or _region.json    canton (CH), grid area (NL), voltage level (FR)
  tariffs/<country>/<region>/<utility>_<year>.json           utility, grid operator connection, supplier
  subsidies/<country>/...              CH per canton, NL and FR per country
  ancillary/<country>.json             rate and reserve, allowed to differ per country
  tech/  capex/  finance/  ems/        default.json, the same everywhere; <country>.json overrides
  business_models/direct_sales.json, eaas.json
parameters.py        load(country, region, utility, year): merges the files, converts shared money
run_case.py          the command line
tests/               checks on invented numbers: python -m pytest elements/battery_reference/tests -q
```

A new utility is a new file `params/tariffs/<country>/<region>/<utility>_<year>.json` (Groupe E in Fribourg:
`CH/FR/GroupeE_2026.json`); a new canton adds its `_canton.json` and `params/subsidies/CH/<canton>.json`; a new
country adds its `_country.json`, `subsidies/<country>/` and `ancillary/<country>.json`. A value marked UNCONFIRMED
in a note is still to be confirmed.

## Checked against the notebook

CH: on 20 Oct 2026 the original SIG notebook and this code ran on the same input workbook (a real site, on Jesse's
laptop only, nothing of it in the repo) with the notebook's settings (its sweep, no EMS capex): every row of the size
sweep and 92 to 93 of the 94 summary values came out exactly equal, the rest within 2.2e-15 relative (the bill is now
summed by component), for 0 Voltiris modules and for 2500 modules under direct sales and under EaaS. Python 3.13,
pypsa 1.3.0, linopy 0.9.1, pandas 3.0.5, numpy 2.5.2. With the new defaults (sweep 100 to 1500 kWh, EMS capex
917 CHF) the same site keeps the same battery (1,236 kWh, regime B, same yearly value); its payback goes from 3.12 to
3.14 years.

NL and FR are not compared with their old notebooks: they now use the CH backbone (tech, capex, replacements,
ancillary reserve, PV must run, the no-battery LP, the one-meter rule), the official TURPE 7 rates and the official
Westland Infra rates (24.4839 EUR/kW/yr and 3.0860 EUR/kW/month; the notebook rounded them), so their numbers
differ by design. Their calendars, prices and charges are checked by the tests against the sources; at negative prices
the one-meter rule is within about 0.1% of an exact switch per quarter hour.

Not carried over: the notebook's charts, the HTML report, the printed tables, the FiT sensitivity and the Dashboard
(they change no result); the NL notebook's imbalance premium (out of scope).

## For Paul

**The model engine leads.** Jesse's decision (22 Oct): the interface adapts to the model, not the other way around.
The model does not have to fit `sizing_input.csv` or the site's step 4 to 6 as they are today; where the two
differ, the site follows the model. The differences are flagged here and left as they are for now:

1. **The tariff goes to the model as parameters, not only as a buy and a sell price per 15 minutes:** capacity
   charges (SIG's monthly HP peak with the annual ratchet, NL's year and month peaks, the French TURPE staircase),
   regimes (SIG A/B by DUP, TURPE LU/CU), peak hours per weekday (the site's `prices.ts` counts weekdays only), an
   export price that is either fixed or the day-ahead series, and the supply contract's export rule (FR: the battery
   exports only PV energy).
2. **Tariffs per region and utility**, under the country (CH: canton and utility; NL: grid operator and connection;
   FR: voltage level and supplier); the site has countries only.
3. **These parameter files are the source** for the battery, tariff, subsidy, ancillary and EMS numbers. The site's
   reference rows differ from them today:

   | | Site (`price_templates`, `subsidies`, `price_list`) | This model |
   |---|---|---|
   | Ancillary | 175 CHF/kW/yr | 90 CHF/kW/yr (98.1 EUR) on 25% of the battery |
   | Battery price | tiers 459 to 229 per kWh | flat 400 CHF/kWh (436 EUR) |
   | CH subsidy | Pronovo 18% | 75% up to the OCAN size |
   | Battery replacements | full price | 60% of the price |
   | EMS | none | 2,500 CHF/yr (2,725 EUR) + 917 CHF (1,000 EUR) capex, fees |

4. **Finance is done in the model** (payback, lifetime profit, replacements, EMS, subsidies), where the site does
   its own in step 6 (`bizcase.ts`); one of the two has to give way, and per the decision above it is the site.
5. **The result shape differs**: the site expects one row per module count and battery size; the model returns one
   study (one module count, a sweep over battery sizes, the chosen size with its bills, monthly tables and payback).
6. **Where it runs**: the site runs its models in the browser (Pyodide); this model uses PyPSA and takes 35 to 80 s
   per battery size natively (see Run time), so it most likely needs the plan's fallback (a Cloudflare Container, decision D7).

How this plugs into the size contract (size 2.0.0, plan 4.6 and 4.8) is left to Paul.
