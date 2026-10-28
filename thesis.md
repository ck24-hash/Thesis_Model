# Thesis context: A Path to Greenhouse Self-Sufficiency: Heat and CO2

Master thesis at EPFL, in collaboration with Voltiris. This file describes the logic of the thesis so that Claude Code can build and extend the techno-economic model consistently.

## 0. Rules for Claude Code

- Never invent parameter values (prices, efficiencies, costs, emission factors, capacities). Use a named placeholder in the config and mark it `TODO [TO CHECK]`.
- Every modelling choice that is not given in this file or in the scenario figure is an assumption. Register it in section 5 and in the code (`ASSUMPTIONS.md` or a docstring with the assumption ID).
- Keep the model modular: one class or function per block, scenarios defined by which blocks are active, not by separate code paths.
- Every timestep must close the heat, electricity and CO2 balances. Add a test that fails if any balance has a residual above a small tolerance.
- Units: kW, kWh, kg CO2, CHF or EUR (one currency in the model, conversion in the inputs), temperatures in degC in inputs and K in equations.
- Default resolution: hourly, 8760 h per year. Keep the timestep as a parameter `dt`.
- Do not model Voltiris optics. Voltiris is an hourly electricity profile (kW per kW installed or per m2) plus, optionally, an effect on greenhouse demand [TO CHECK].
- Keep answers and code comments plain and short. No generic sustainability text.

## 1. Thesis scope

Goal: assess how a commercial greenhouse can become more self-sufficient in heat, CO2 and electricity by combining:

- greenhouse demand
- Voltiris on-site electricity production
- decentralized or modular data center (DC) with waste heat recovery
- heat pump (HP)
- solid oxide fuel cell (SOFC)
- thermal storage (TS)
- backup heating
- grid interaction
- CO2 supply and enrichment

The model compares scenarios (baseline, S1 to S4 with variants) on heat, CO2 and electricity self-sufficiency, cost, payback, emissions and component sizing, for Switzerland, France and the Netherlands.

Each model question should be placed along four axes: which block, which flow (heat, electricity, CO2, money, emissions), which part of the work (technical model, financial model, literature review, case study, scenario comparison), and whether it helps compare configurations.

## 2. Scenarios (from Scenarios.png)

Fuels: natural gas (NG) for boiler and CHP, ethanol for SOFC. Each fuel has its own price and emission factor.

### 2.1 Block activation matrix

| Block | Base | S1 | S2 | S2+Bat | S2+Bat+ExtCO2 | S3 | S3+Bat | S3+Bat+ExtCO2 | S4 |
|---|---|---|---|---|---|---|---|---|---|
| Greenhouse | x | x | x | x | x | x | x | x | x |
| NG boiler | x | backup | x | x | - | x | x | - | - |
| CHP (NG) | - | x | - | - | - | - | - | - | - |
| Voltiris | - | - | x | x | x | x | x | x | x |
| Heat pump | - | - | x (ambient) | x (ambient) | x (ambient) | x (DC) | x (DC) | x (DC) | x (DC) |
| Thermal storage | x | x | x | x | x | x | x | x | x |
| Battery | - | - | - | x | x | - | x | x | x |
| Data center | - | - | - | - | - | x | x | x | x |
| SOFC (ethanol) | - | - | - | - | - | - | - | - | x |
| External liquid CO2 | - | - | - | - | x | - | - | x | - |
| Grid | import | import+export | imp+exp | imp+exp | imp+exp | imp+exp | imp+exp | imp+exp | imp+exp |

### 2.2 Scenario descriptions

Baseline: NG boiler supplies heat and CO2 (flue gas) to the greenhouse and charges thermal storage. Electricity from the grid (import only). This is the reference for savings, payback and avoided emissions.

S1 (CHP): NG CHP supplies electricity, heat and CO2 to the greenhouse and charges storage. Surplus electricity exported to the grid. A backup boiler (NG) covers heat peaks and can also supply CO2 and charge storage.

S2 (Voltiris + HP): Voltiris supplies the greenhouse, the HP and the grid (export). The HP takes low-temperature heat from the environment (ambient) and delivers heat to the greenhouse and to storage. The NG boiler stays as backup and as CO2 source.
- S2 + Battery: battery connected to Voltiris, HP, greenhouse and grid.
- S2 + Battery + Ext. CO2: boiler and NG supply removed. CO2 comes from purchased liquid CO2. Heat comes only from HP and storage, so a backup assumption is needed (A1).

S3 (Voltiris x Data Center): as S2, plus a DC powered by Voltiris (and grid). DC waste heat is the HP heat source. Same three variants as S2 (base, +Battery, +Battery +Ext. CO2, last one without boiler).

S4 (complete system): Voltiris x DC x SOFC. Ethanol-fed SOFC supplies electricity, heat and CO2 to the greenhouse. HP uses DC heat. Thermal storage, battery and grid are present. No boiler and no external CO2 in the figure.

### 2.3 Flow rules

- DC heat reaches the greenhouse only through the heat pump. There is no direct DC to greenhouse or DC to storage heat flow in the model.
- Heat demand must always be met. Where no boiler is drawn (S2+Bat+ExtCO2, S3+Bat+ExtCO2, S4), a backup is still needed. See A1.
- Any flow not drawn in the figure is an assumption. They are listed in section 5.

## 3. Blocks

For each block: role, inputs, parameters, outputs, constraints. All numeric parameters are `[TO CHECK]` until sourced.

### 3.1 Greenhouse (central demand)

Role: demands heat, CO2 and electricity.
- Heat demand `Q_gh(t)` [kW]: from measured data if available, otherwise from a simple dynamic model (envelope loss, ventilation, solar gain, setpoints, crop schedule, possibly night screens). Climate files per country needed.
- CO2 demand `M_co2_gh(t)` [kg/h]: depends on setpoint, crop, ventilation openings and daylight (enrichment only when photosynthesis is active). Drops when vents are open. Needs a ventilation proxy from weather.
- Electricity demand `P_gh(t)` [kW]: fans, pumps, screens, control, possibly lighting. Lighting is a large decision [TO CHECK with Voltiris whether lighting is in scope].
- Parameters: floor area, heating supply temperature level, return temperature, CO2 setpoint.
- Optional: effect of Voltiris shading on heat demand and CO2 uptake [TO CHECK, probably out of scope].

### 3.2 Voltiris

Role: local electricity generation `P_vol(t)` [kW], hourly profile from location weather. Treated as a black box profile times installed capacity.
- Parameters: installed capacity, specific yield profile, CAPEX, OPEX, degradation (optional).
- Outputs go to: greenhouse, DC, HP, battery, grid export. Curtailment allowed (variable `P_curt`).
- Open: what is Voltiris capacity relative to greenhouse area, and is it a sizing variable or fixed? [TO CHECK with Voltiris]

### 3.3 Data center (DC)

Role: electricity consumer and heat source for the HP.
- Electricity `P_dc(t)` [kW]: IT load profile (flat or variable) times PUE-like overhead for cooling and auxiliaries.
- Heat output `Q_dc(t)` ~ essentially all IT electricity ends as heat.
- Recoverable fraction `f_rec` [-]: share of `Q_dc` that can be captured at a usable temperature level (liquid cooling vs air cooling changes this a lot).
- Temperature level `T_dc` [degC]: sets the HP source temperature and hence COP.
- Continuity: DC uptime requirement. If the DC needs reliable power, Voltiris alone is not enough, so grid, battery or SOFC must cover.
- Heat that the HP does not take must be rejected to the environment (dry cooler or chiller, with its own electricity). Rejected heat is an output.
- Business-model constraints: who owns the DC, who pays for electricity, does the greenhouse pay for the heat, DC SLAs, DC load tied to compute demand rather than to greenhouse heat demand [TO CHECK].
- Parameters: capacity [kW IT], `f_rec`, `T_dc`, overhead factor, CAPEX (treatment in the economics is an open decision, see A9).
- Output: recoverable heat available to the HP `Q_dc_avail(t) = f_rec * P_dc(t)`.

### 3.4 Heat pump (HP)

Role: converts electricity and a low-temperature source into heat for the greenhouse and for storage.
- Source: environment (S2) or DC waste heat (S3, S4).
- Equations:
  - `Q_hp = COP * P_hp`
  - `COP = eta_carnot * T_sup / (T_sup - T_src)` with temperatures in K, `eta_carnot` a fraction [TO CHECK]. A manufacturer COP curve can replace this.
  - Source heat drawn: `Q_src = Q_hp - P_hp`. For DC source: `Q_src <= Q_dc_avail`.
- Parameters: thermal capacity, minimum load, `eta_carnot` or COP map, supply temperature (greenhouse direct vs storage charging may differ), CAPEX, OPEX.
- Electricity from: Voltiris, SOFC (S4), battery, grid.
- Heat to: greenhouse directly or thermal storage.
- Constraints: capacity limit, minimum part load, max supply temperature, COP floor when source is cold (S2 ambient).

### 3.5 SOFC (S4 only, ethanol)

Role: electricity, high-temperature heat, CO2-rich exhaust.
- Fuel input `F_sofc(t)` [kW LHV].
- `P_sofc = eta_el * F_sofc`, `Q_sofc = eta_th * F_sofc`, with `eta_el + eta_th <= 1` [TO CHECK values].
- CO2 output `M_co2_sofc = ef_fuel * F_sofc`. Stoichiometric reference for ethanol: 2 mol CO2 per mol ethanol, which is about 1.91 kg CO2 per kg ethanol. Check how much of this is usable after conditioning, and the exhaust composition.
- Constraints: rated capacity, minimum load, ramp rate, start-up time and cost, limits on thermal cycling, degradation, stack replacement. SOFCs run best at near-constant load, which conflicts with a variable CO2 and heat demand.
- Open: ethanol is biogenic or fossil depending on origin, which changes emission accounting [TO CHECK]. Exhaust CO2 conditioning step (cooling, cleaning) cost and losses.
- Role in S4: supply greenhouse electricity, possibly DC and HP electricity (A6), supply heat and CO2.

### 3.6 CHP (S1 only, NG)

Role: electricity, heat, flue gas CO2.
- Same structure as SOFC with `eta_el`, `eta_th`, NG fuel. CO2 from flue gas needs cleaning before enrichment [TO CHECK, depends on whether the greenhouse uses it directly].
- Operating modes to test: heat-led, CO2-led, electricity-price-led.
- Constraints: capacity, minimum load, start/stop, export limit.

### 3.7 Thermal storage (TS)

Role: shift heat in time.
- State `E_ts(t)` [kWh]. Update:
  `E_ts(t+1) = E_ts(t) * (1 - loss_rate * dt) + eta_ch * Q_ch(t) * dt - Q_dis(t) * dt / eta_dis`
- Parameters: capacity, max charge and discharge power, loss rate, temperature level, min and max SOC, initial and final SOC, CAPEX per kWh.
- Charged by: boiler, CHP, SOFC, HP. Discharges to: greenhouse only.
- Storage losses go to environment (reported).
- Closed cycle constraint: `E_ts(end) >= E_ts(start)` to avoid free energy.

### 3.8 Battery

Role: electricity shifting, raises Voltiris self-consumption.
- State `E_bat(t)`, charge and discharge efficiency, power limit, SOC limits, optional degradation, CAPEX per kWh and per kW.
- Present only in listed variants and S4.
- Connected to Voltiris, HP, greenhouse, grid (as in the figure). In S3/S4 it also serves the DC through the electrical bus.

### 3.9 Grid

Role: balancing source and sink.
- Import `P_imp(t)`, export `P_exp(t)`, both with limits (connection capacity).
- Price per country: import tariff (energy + network + taxes, time-varying if relevant), export price, capacity or peak charges [TO CHECK].
- Value of self-consumption = avoided import price minus the forgone export price.
- Import and export not simultaneous at the same timestep (constraint or cost penalty).

### 3.10 Conventional boiler (backup heating)

Role: NG heat source, also CO2 source in baseline, S2, S3.
- `Q_boiler = eta_b * F_boiler`, `M_co2_boiler = ef_ng * F_boiler`.
- Parameters: capacity, efficiency, minimum load, CAPEX (often sunk in retrofit cases, see A8).
- In S2/S3 the boiler is "backup and CO2 source": it may run for CO2 even when heat is not needed, and send the surplus heat to storage or reject it. Treat as an operating option (A4).

### 3.11 External CO2 supply

Role: purchased liquid CO2 replacing flue gas CO2.
- Price per kg [TO CHECK per country], delivery constraints, tank size (not drawn, A7), supply is not limited except by cost.
- Netherlands: pipeline CO2 supply to greenhouse clusters exists (OCAP); check availability and price [TO CHECK]. Not drawn in the figure, so only relevant as a sensitivity.

### 3.12 Auxiliary electric heater (assumption, not in figure)

Role: guarantee heat coverage where no boiler exists (see A1).
- Resistance heater, COP = 1, capacity sized to the peak unmet heat. It draws grid or local electricity.
- Its capacity is a reported output ("required backup heating").

## 4. Flows and balances

### 4.1 Heat

Greenhouse heat balance (supply-level heat):
```
Q_gh(t) = Q_boiler_gh + Q_chp_gh + Q_sofc_gh + Q_hp_gh + Q_ts_dis + Q_aux
```
Storage inflow: `Q_ch = Q_boiler_ts + Q_chp_ts + Q_sofc_ts + Q_hp_ts`.

Low-temperature heat side (S2 to S4):
```
Q_src_hp = Q_hp - P_hp
S3, S4:  Q_src_hp <= f_rec * P_dc
Q_dc_rejected = Q_dc_total - Q_src_hp    (unused DC heat)
```
Other heat losses: storage losses, unused SOFC heat, unused boiler or CHP heat when running for CO2 or electricity.

### 4.2 Electricity

One site bus per timestep:
```
P_vol + P_chp + P_sofc + P_imp + P_bat_dis
  = P_gh + P_dc + P_hp + P_aux_el + P_exp + P_bat_ch + P_curt
```
Terms exist only for active blocks. DC cooling and heat rejection electricity is part of `P_dc` or `P_aux_el` (A10).

### 4.3 CO2

```
M_co2_gh_supplied = M_boiler + M_chp + M_sofc_used + M_ext
M_co2_gh_supplied <= M_co2_gh(t)        (no oversupply to greenhouse)
M_vented = M_available - M_co2_gh_supplied   (unused CO2)
```
CO2 is produced only while fuel is burned. This is the main coupling problem: heat demand and CO2 demand do not follow each other (summer: CO2 needed in the day, heat not). CO2 storage is not drawn (A7).

### 4.4 Fuel and money

Fuel energy: `F_ng` (boiler, CHP), `F_etoh` (SOFC), each with price and emission factor.
Money flows: investment, O&M, fuel, grid import cost, export revenue, CO2 purchase, heat value (section 8).

## 5. Assumptions register

Keep this list in the code repo and update it. IDs are used in code comments.

- A1 Backup where no boiler is drawn (S2+Bat+ExtCO2, S3+Bat+ExtCO2, S4): add an auxiliary electric resistance heater fed from the electricity bus (grid first). Its peak is reported as required backup heating. Alternative: oversize the HP. Test both.
- A2 Grid to battery charging and battery to grid export are allowed in battery scenarios (figure shows battery-grid links). Make it switchable.
- A3 S3 and S4 HP source is DC heat only, since no environment arrow is drawn there. When `Q_dc_avail` is too low (DC off or low load), the HP cannot run at full output. Option: allow ambient as a fallback source. Default: DC only, and the shortfall goes to backup.
- A4 In scenarios with a boiler, the boiler may run for CO2 even without heat demand (heat sent to storage or rejected). Switchable operating mode.
- A5 Boiler heat reaches the greenhouse directly and through storage, as drawn. Storage discharges to the greenhouse only (never to HP or DC).
- A6 In S4 the SOFC electricity reaches the DC and HP through the shared electrical bus. The figure shows SOFC to greenhouse and a line toward battery and grid. Confirm with the author.
- A7 No CO2 storage or buffer tank is modelled in the base case. Option: small buffer.
- A8 Boiler CAPEX is sunk in reference cases (existing greenhouse). In scenarios where the boiler is removed, no resale. Switchable.
- A9 DC CAPEX and revenue: default is that the DC is an exogenous asset. Only the electricity it uses and the value of its heat enter the greenhouse economics. Alternative: include DC CAPEX in the system. Needs a decision (business model).
- A10 DC electricity includes cooling and heat rejection. Rejected heat is not recovered.
- A11 S4 has no external CO2. CO2 shortfalls when the SOFC is off are recorded as unmet CO2 (CO2 self-sufficiency below 100 %), with an optional yield or cost penalty.
- A12 Voltiris effect on greenhouse heat and CO2 demand is ignored unless data is provided.
- A13 Grid emission factor is constant per country by default. Option: hourly.
- A14 Single greenhouse, one electrical connection point, no internal network losses.

## 6. Constraints (summary)

- Balances for heat, electricity, CO2 closed at each timestep.
- Capacity limits per block, minimum loads where relevant (HP, SOFC, CHP, boiler).
- SOFC and CHP ramp rate, start-up and cycling limits.
- Storage SOC bounds, charge and discharge power limits, closed-cycle condition.
- Battery SOC bounds, power limits.
- Grid import and export limits, no simultaneous import and export.
- HP: COP depends on source and supply temperature. DC source limited by recoverable heat.
- DC heat only reaches the greenhouse via the HP.
- Greenhouse heat demand is always met (via backup if needed).
- CO2 supplied to the greenhouse cannot exceed demand, excess is vented.
- DC continuity requirement (reliability of its electricity supply).

## 7. Operating logic and objective

Two stages are recommended.

Stage 1: rule-based hourly dispatch for fixed sizes (simple, transparent, easy to debug). Proposed priority, to be validated:
- Electricity: Voltiris to DC, HP and greenhouse loads first, then battery charge, then export. Deficit from battery, then SOFC or CHP, then grid.
- Heat: DC-sourced HP and direct SOFC heat first, then storage, then ambient HP (S2), then boiler, then auxiliary heater.
- CO2: SOFC or CHP or boiler exhaust when running, then external CO2 for the remainder.
- SOFC mode: constant load, heat-led or CO2-led (to be compared).

Stage 2: optimization (LP or MILP, for example Pyomo or PuLP with an open solver) to size components and dispatch together:
```
min  annualized_CAPEX + O&M + fuel + grid_import_cost - export_revenue + CO2_purchase + penalties(unmet CO2, backup)
s.t. balances, capacities, storage and battery dynamics, grid limits
```
Decision variables: capacities (HP, TS, battery, SOFC, DC, Voltiris if free, backup) and hourly flows. A typical week or a set of representative days can replace 8760 h if the solve time is too long, but check the error against the full year.

Do not claim an optimum from the rule-based run. Report which stage a result comes from.

## 8. Economics

- Annualized investment: `CAPEX_ann = CAPEX * CRF`, with `CRF = r(1+r)^n / ((1+r)^n - 1)`. Lifetime `n` per component and discount rate `r` [TO CHECK].
- Annual cost = `CAPEX_ann + fixed O&M + variable O&M + fuel + grid import + backup + CO2 purchase - export revenue - heat value (if sold)`.
- Annual savings = baseline annual operating cost minus scenario annual operating cost.
- Simple payback = `ΔCAPEX / annual savings` vs baseline.
- NPV and IRR on the yearly cash flow difference vs baseline, over a project horizon [TO CHECK]. Only compute IRR if CAPEX and price data are real inputs.
- Replacement costs (SOFC stack, battery) in the cash flow.
- Heat recovery value: depends on the business model (A9). Options: heat given free, heat priced at avoided cost, shared savings.
- Price inputs per country: NG, ethanol, electricity import and export, CO2 price (liquid supply), carbon tax or levy where it applies [TO CHECK].
- Subsidies and feed-in schemes: reported separately, not in the base result.

## 9. Environmental indicators

- Emissions = fuel use * fuel factor + grid import * grid factor, minus an export credit if used (state the method).
- Avoided emissions vs baseline.
- Ethanol: biogenic or fossil must be stated (A13 and section 3.5).
- CO2 from the flue gas used in the greenhouse is not counted as a reduction by itself, since it is only utilised. State the accounting boundary.
- Optional: emissions per kg of crop if yield data is available.

## 10. Outputs

For each scenario, country and weather year:
- Heat self-sufficiency, CO2 self-sufficiency, electricity self-sufficiency (definitions below).
- Total annualized cost, annual savings, payback, IRR (if possible).
- Grid import and export (kWh/year, peak kW).
- Fuel consumption (NG, ethanol).
- Emissions and avoided emissions.
- Thermal storage size and utilization (cycles, mean SOC).
- HP electricity, seasonal COP.
- DC waste heat utilization = heat used by HP / total DC heat.
- Required SOFC capacity, required DC capacity, required backup heating.
- Rejected heat (DC, SOFC, boiler or CHP), vented CO2, curtailed Voltiris electricity.

Definitions (fix them once in code and report which are used):
- Heat self-sufficiency = heat from on-site non-grid, non-fossil-backup sources / heat demand. State separately whether HP electricity from the grid counts. A cleaner version: `1 - (backup heat + grid-electricity-driven heat) / heat demand`. Choose one and keep it.
- CO2 self-sufficiency = CO2 from on-site sources (SOFC, CHP, boiler) / CO2 demand. Purchased liquid CO2 is not self-supplied.
- Electricity self-sufficiency = local electricity used on site / total site demand.
- Self-consumption = local electricity used on site / local electricity produced.

## 11. Scenario comparison

Always compare against the baseline using the same demand, weather and price year. Table per country: cost, savings, payback, emissions, the three self-sufficiency values, required backup, key sizes. Highlight what changes between steps:
- Baseline to S1: electricity and CO2 from CHP, heat-led operation, export income.
- S1 to S2: replacing gas heat with Voltiris-powered HP, loss of free CO2 when boiler runs less.
- S2 to S2+Bat: self-consumption gain versus battery cost.
- S2+Bat to ExtCO2: boiler removal, CO2 purchase cost vs fuel saving, backup need (A1).
- S2 to S3: DC adds electricity load and a better HP source, extra DC electricity must be sourced.
- S3 to S4: SOFC adds electricity, heat, CO2, but with ethanol cost and SOFC constraints.

## 12. Countries

Switzerland, France, Netherlands. For each, collect as inputs (not hardcoded numbers):
- Climate and weather file (heating degree hours, solar profile).
- Greenhouse heat demand profile for a representative crop.
- Electricity import tariff structure, export price, network charges, peak charges.
- NG price, ethanol price, liquid CO2 price, carbon levy.
- Grid carbon intensity.
- CO2 sourcing options (liquid CO2, pipeline, flue gas).
- Regulation: CHP and fuel cell support, heat network rules, DC permitting, greenhouse CO2 rules, grid connection limits.
- Practical feasibility: grid congestion, DC siting, SOFC availability and service, ethanol supply.

Known qualitative points to verify [TO CHECK]: the Netherlands has a strong CHP and pipeline CO2 tradition and grid congestion in some regions. France has a low-carbon electricity mix. Switzerland has a CO2 levy on heating fuels with exemptions that need checking for greenhouses.

## 13. Sensitivity analysis

One-at-a-time first, then selected pairs:
- Electricity import price, export price, NG price, ethanol price, liquid CO2 price.
- Heat demand level and weather year.
- Voltiris capacity and yield.
- HP COP (`eta_carnot`, supply temperature), DC temperature level.
- DC size, load profile, `f_rec`.
- SOFC efficiency, minimum load, CAPEX, fuel price.
- Storage and battery size and cost.
- Discount rate, lifetime.
- Grid emission factor.
- Backup assumption A1 (resistance heater vs oversized HP).

Report break-even values where a scenario overtakes the baseline or another scenario.

## 14. Data needed (to confirm assumptions)

- Real greenhouse heat, CO2 and electricity demand (hourly) or the crop and climate settings to generate them.
- Voltiris hourly production profile and installed capacity range.
- DC IT load profile, cooling type, coolant temperature, recoverable fraction.
- HP manufacturer COP data at relevant source and supply temperatures.
- SOFC datasheet: efficiencies, minimum load, ramping, ethanol reformer, exhaust CO2 purity.
- Component CAPEX, O&M, lifetime for each block.
- Price time series per country.
- Business model decisions for the DC (A9).

## 15. Suggested code structure

```
thesis_model/
  config/            # scenarios.yaml, countries.yaml, components.yaml (placeholders TODO [TO CHECK])
  data/              # weather, prices, demand profiles
  blocks/            # greenhouse.py, voltiris.py, datacenter.py, heatpump.py, sofc.py, chp.py,
                     # boiler.py, storage.py, battery.py, grid.py, co2_supply.py, aux_heater.py
  dispatch/          # rules.py (stage 1), optimization.py (stage 2)
  economics/         # annuity, payback, NPV, IRR
  emissions/
  scenarios/         # builds block set per scenario from the activation matrix
  analysis/          # KPIs, comparison tables, sensitivity runs, plots
  tests/             # balance closure, storage energy conservation, COP bounds, scenario wiring
```

Implementation notes:
- Scenarios are defined as data (which blocks are active, which links are allowed). Flows not drawn in the figure are links switched by assumption flags.
- Every block returns its flows in a common time series DataFrame so the balance tests can run on any scenario.
- Log which assumption flags were active for each result.
- Start with the baseline and S1 (simplest), validate balances, then add S2, S3, S4.
