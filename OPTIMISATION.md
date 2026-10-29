# How the model optimises

This file explains every optimisation in the model: the yearly dispatch, each block's sizing study, the joint sizing,
and what is computed from their results (the electricity side, the site's yearly cost, the comparison of two
scenarios). Each section gives the formulas, then why it is done that way. The code it describes is named at the start
of each section. Assumption IDs (A1 to A20) refer to `thesis.md` section 5.

Values written TO CHECK in the parameter files are placeholders, not sourced data.

## 1. The overall approach

Two kinds of decisions are taken:

- **Operation**: how each unit runs at every quarter hour of the year (grid import and export, battery charging,
  boiler output, heat storage). For given sizes, this is one linear programme over the whole year.
- **Sizing**: the size of each sized block (battery in kWh, gas boiler in kW of heat, heat storage in kWh of heat).
  Either each block's own study tries a list of sizes, solving the year for each, or the joint sizing makes the sizes
  variables of the same linear programme.

Every optimisation minimises cost, with **perfect foresight** over one year (the solver knows every price and
demand of the year in advance). This gives the best a system can do, so it is an upper bound on what a real
controller would reach. A real energy management system, which only forecasts, would do somewhat worse (A-series in
`thesis.md`; the battery's peak shaving realisation factor in `general/commercial` is a reminder of this).

Time: 35,040 steps of $\Delta t = 0.25$ h. Coarser input data is repeated (kW, prices, temperatures) or divided (kWh
per step) to 15 min (`common/timeseries.py`). The solver is HiGHS through PyPSA.

## 2. Notation

| Symbol | Meaning | Unit |
|---|---|---|
| $t \in T$ | time step (35,040 a year), $\Delta t = 0.25$ h | |
| $L_t$ | electricity load of the greenhouse | kW |
| $PV_t$ | PV output on site (Voltiris + existing PV) | kW |
| $s_t$ | Voltiris share of the PV at $t$: $PV^{V}_t / PV_t$ | |
| $I_t, E_t$ | grid import and export | kW |
| $c^{imp}_{t,r}$ | import price at $t$ under regime $r$ (all energy and network components) | per kWh |
| $v_t$ | value of 1 kWh exported for the grower (section 3.4) | per kWh |
| $c^+_t, c^-_t$ | battery charging (taken from the bus) and discharging (given to the bus) | kW |
| $e_t$ | energy in the battery | kWh |
| $H_t$, $C_t$ | heat demand (kW) and CO2 demand (kg/h) of the greenhouse | |
| $g_t$ | gas burnt by the boiler | kW (of gas, lower heating value) |
| $q^{b}_t$ | boiler heat output | kW |
| $q^{in}_t, q^{out}_t$ | heat into, and out of, the heat storage | kW |
| $h_t$ | heat in the storage | kWh |
| $p^{gas}_t$ | gas price | per kWh |

## 3. The yearly dispatch

`system/dispatch.py` builds one network from the chosen blocks (each block adds its own components) and solves it.

### 3.1 Objective

$$
\min \; \sum_t \Big[ c^{imp}_{t,r} I_t - v_t E_t \Big]\Delta t
\;+\; \text{capacity charges}
\;+\; \sum_t \Big[ (p^{gas}_t + \lambda \, \varepsilon)\, g_t + m^{b}\, q^{b}_t \Big]\Delta t
\;+\; \sum_t \Big[ \pi^{H} u^{H}_t + \pi^{C} u^{C}_t \Big]\Delta t
$$

- grid import cost minus export value, and the capacity charges (section 3.3);
- gas at its price plus the carbon levy $\lambda$ (per kg CO2) times the emission factor $\varepsilon$ (kg CO2 per
  kWh of gas), and the boiler's variable O&M $m^b$ per kWh of heat;
- unmet heat $u^H_t$ and unmet CO2 $u^C_t$ at penalties $\pi^H, \pi^C$ (10 per kWh and per kg). The penalties are
  solver devices, not prices (A15): they keep the year solvable when a unit is too small, and a size that needs them
  is reported as not covering the demand.

Fixed costs (investments, fixed O&M) do not depend on operation and are not in the dispatch. They enter the sizing.

### 3.2 Electricity bus

At every step, what enters the site's bus equals what leaves it:

$$ PV_t + I_t + c^-_t = L_t + E_t + c^+_t $$

The PV must run: Voltiris and existing PV are one generator whose output is fixed to their summed output
$PV_t = N \cdot y_t / 1000 + PV^{ex}_t$ ($N$ modules, $y_t$ the yield of one module in W). They share the one meter
of the site, as in the reference model, so they are one generator.

### 3.3 Grid

$$ 0 \le I_t \le \bar I, \qquad 0 \le E_t \le \bar E $$

$\bar I, \bar E$: the case's connection limits, else $2 \max_t L_t$ and $1.1 \max_t PV_t$.

**Import price.** $c^{imp}_{t,r}$ is the sum of the tariff's components at $t$ (energy, network, levies), each fixed
by period (peak and off-peak windows) or based on the day-ahead price, for the regime $r$.

**Capacity charges**, added to the objective as linear constraints on peak variables:

- monthly peak in a window $W$: a variable $P_m \ge I_t$ for every $t$ of month $m$ in $W$, cost
  $\text{rate}_r \cdot P_m$ per month. With an annual ratchet, $P_m \ge P_{m-1}$, so the billed peak never falls
  during the year;
- yearly peak: $P \ge I_t$ for $t$ in $W$, cost $\text{rate}_r \cdot P$;
- staircase (FR TURPE): one peak per time slot, each slot's peak at least the previous slot's,
  $P_{k} \ge P_{k-1}$, cost $\sum_k (b_k - b_{k+1}) P_k$. This is how the TURPE weighted power is written as a
  linear cost.

Minimising cost with peak variables bounded from below gives exactly the billed peak: the solver has no reason to
make $P_m$ larger than the highest import.

**Regime and DUP (CH).** Some tariffs have two regimes chosen by the hours of use
$DUP = \sum_t I_t \Delta t \, / \, \max_{t \in \text{peak}} I_t$: regime A at or below the threshold
(3,000 h for SIG), regime B above. The regime changes the prices, which changes the import, which changes the DUP. The
model:

1. finds the starting regime from the DUP of $(L_t - PV_t)^+$ (the site without battery);
2. solves under that regime;
3. if a solution's DUP falls on the other side of the threshold, solves it again twice, with the DUP held in each
   regime by the linear constraint $\theta P_{Dec} - \sum_t I_t \Delta t \ge 0$ (A) or $\le 0$ (B), $P_{Dec}$ the
   year's billed peak, and keeps the cheaper.

### 3.4 Business model on the exports

The grower's value of an exported kWh:

- direct sales: $v_t$ = the feed-in (fixed, or the day-ahead price);
- EaaS (Voltiris owns the modules, the grower pays a price $p^{E}$ per MWh of Voltiris energy used on site): the
  grower's PV cash flow is $(1-s_t)\,FiT_t\,E_t - p^{E} s_t (PV_t - E_t)$, which equals
  $v_t E_t - p^{E} s_t PV_t$ with $v_t = (1-s_t) FiT_t + s_t\,p^{E}$. The last term does not depend on the dispatch,
  so the dispatch only needs $v_t$; the fee goes back into the bills.

Under EaaS the site exports exactly its PV surplus and imports nothing while it has one (bounds on $I_t$ and $E_t$),
since otherwise the solver would import cheap power and export Voltiris power at the same moment.

### 3.5 Battery

For a bought size $B$ (kWh), with depth of discharge window $w = s^{max} - s^{min}$, C-rate $\kappa$ and a reserve
share $r$ kept for ancillary services (per country):

$$ 0 \le e_t \le (1-r)\,w\,B, \qquad 0 \le c^+_t, c^-_t \le (1-r)\,\kappa B $$

$$ e_t = (1-\sigma)^{\Delta t}\, e_{t-1} + \Delta t \Big(\eta^{+} c^+_t - \frac{c^-_t}{\eta^{-}}\Big), \qquad e_{0} = e_{|T|} \;\text{(cyclic)} $$

$\sigma$: self-discharge per hour (the daily value / 24), $\eta^+, \eta^-$: charge and discharge efficiencies.
The reserve is taken out of both the energy window and the power, so the dispatch only uses what is not sold to the
grid operator.

**One meter** (where cheating could pay: steps where exporting is worth more than importing, or with a negative
price; never in CH). A single meter cannot import and export at once, nor charge and discharge at once. Within a
quarter hour both may happen one after the other, so with shortfall $D_t = (L_t - PV_t)^+$, surplus
$S_t = (PV_t - L_t)^+$ and battery power $P$:

$$ c^+_t + c^-_t \le P, \qquad I_t \le D_t + \max(1 - S_t/P, 0)\,c^+_t, \qquad E_t \le S_t + \max(\eta^- - D_t/P, 0)\,c^-_t $$

These limits are exact for the step's averages (time sharing), and linear because $D_t, S_t$ are fixed numbers.

**PV-only export** (a contract that only pays for PV energy exported). The battery keeps an account $a_t$ of the PV
energy it holds:

$$ 0 \le c^{PV}_t \le \min(S_t, c^+_t), \quad 0 \le d^{PV}_t \le c^-_t, \quad
a_t = (1-\sigma)^{\Delta t} a_{t-1} + \Delta t(\eta^+ c^{PV}_t - d^{PV}_t), \quad 0 \le a_t \le e_t $$

$$ E_t \le S_t - c^{PV}_t + \eta^- d^{PV}_t $$

so grid energy stored in the battery serves the site but is never exported.

### 3.6 Heat side

Added when the system has a heat block. Buses: heat, CO2, gas.

**Gas supply**: a generator on the gas bus, cost $p^{gas}_t + \lambda\varepsilon$ per kWh of gas.

**Gas boiler** of size $Q$ (kW of heat), efficiency $\eta^{b}$, usable share of the flue gas CO2 $\phi$:

$$ q^{b}_t = \eta^{b} g_t \le Q, \qquad \text{CO2 to the CO2 bus} = \varepsilon\,\phi\, g_t \;\text{(kg/h)} $$

**Heat bus** at every step:

$$ q^{b}_t + q^{out}_t + u^{H}_t = H_t + q^{in}_t + z^{H}_t $$

$z^H_t \ge 0$ is heat released (free): the boiler may give more heat than needed when it runs for CO2.

**CO2 bus**, CO2 demand that must be met (`co2_mode: required`, A4):

$$ \varepsilon\,\phi\, g_t + u^{C}_t = C_t + z^{C}_t $$

$z^C_t \ge 0$ is CO2 vented. In `by_product` mode there is no CO2 demand in the optimisation: the boiler runs for
heat, and the greenhouse takes $\min(\varepsilon\phi g_t, C_t)$ afterwards; the rest of the demand is reported as
unmet. All the CO2 of the gas burnt counts as emitted, $\varepsilon g_t$ (A17).

**Heat storage** of size $K$ (kWh of heat), power per kWh $\rho$, efficiencies $\eta^{in}, \eta^{out}$:

$$ h_t = (1-\ell_t)^{\Delta t}\, h_{t-1} + \Delta t\Big(\eta^{in} q^{in}_t - \frac{q^{out}_t}{\eta^{out}}\Big),
\qquad 0 \le h_t \le K, \qquad q^{in}_t \le \rho K, \quad q^{out}_t \le \rho K, \qquad h_0 = h_{|T|} $$

The loss share per hour $\ell_t$ (A18):

| Mode | $\ell_t$ |
|---|---|
| constant | $\ell$ |
| seasonal | $\ell_{season(t)}$: winter Dec to Feb, spring Mar to May, summer Jun to Aug, autumn Sep to Nov |
| dynamic | $\ell_{ref} \cdot \dfrac{T_{store} - T^{out}_t}{T_{store} - T_{ref}}$, at least 0 |

The dynamic mode follows heat conduction through the tank walls, proportional to the temperature difference with the
outside, with a fixed mean tank temperature (the tank temperature does not follow the state of charge, which keeps
the loss linear in $h_t$).

## 4. Each block's own study (sizing one at a time)

Used with `"system": {"sizing": "sequential"}`, or when the system has a single sized block. Each study tries a list of
sizes; for each size, the whole year (section 3) is solved with the other blocks fixed. This is exact for each size,
and shows how the result changes with the size. Order: boiler, then heat storage, then battery (A16).

### 4.1 Battery (`elements/battery/study.py`, `sizing.py`; the reference model's study)

1. The year without battery under the starting regime gives the baseline bill $\text{Bill}_0$.
2. For each size $B$ in the list (default 100 to 1,500 kWh in steps of 100, stopping at the subsidised maximum with
   CH's OCAN rule), the year with the battery gives $\text{Bill}_B$, with the regime handling of section 3.3.
3. Its value per year:

$$ V_B = \underbrace{(\text{Bill}_0 - \text{Bill}_B)}_{\text{bill saving}} + \underbrace{A_B}_{\text{ancillary revenue}} - \underbrace{\text{EMS}_B}_{\text{fixed + fees}} $$

   with $A_B = \text{rate} \cdot r\kappa B$ (the reserved power times the yearly rate per kW) and
   $\text{EMS}_B = \text{fixed} + f^{A} A_B + f^{S} \max(\text{Bill}_0 - \text{Bill}_B, 0)$.
4. Investment $I_B$ = battery price after subsidy + EMS hardware; payback $I_B / V_B$; lifetime profit
   $V_B \cdot \text{life} - I_B$.
5. Choice: **profit** (the highest lifetime profit among the sizes that pay back within the battery life, else the
   shortest payback), **payback**, or **custom**.

The bill saving is then split into self-consumption (PV surplus stored instead of exported), arbitrage (grid energy
bought cheap, used dear), capacity charges saved and regime switch, so the value can be explained.

### 4.2 Gas boiler (`elements/ng_boiler/study.py`, `sizing.py`)

1. The size the demand needs: the largest heat at one step, or, when the CO2 demand must be met, the heat that comes
   with burning gas for the CO2:

$$ Q^{need} = \max_t \max\Big(H_t,\; \frac{C_t}{\varepsilon\phi/\eta^{b}}\Big) $$

2. Sizes: $Q^{need} \times \{0.8, 0.9, 1.0, 1.1, 1.25, 1.5\}$, rounded up to 10 kW, or the case's list.
3. For each size: the year's heat, unmet heat and CO2, gas cost, levy, O&M; yearly cost $Y_Q$; investment $I_Q$;
   lifetime cost $I_Q + Y_Q \cdot \text{life}$. A size covers the demand when it leaves nothing unmet (at most
   $10^{-6}$ of the year's demand).
4. Choice: **lowest lifetime cost** among the sizes that cover (default), **smallest** that covers, or **custom**.

Reasoning: all covering sizes burn about the same gas, so a larger boiler only adds investment and fixed O&M. Alone,
the boiler therefore always comes out at the size the demand needs. Its size can only be reduced by something that
takes its peaks: a heat storage, and later a CHP or a heat pump. This is why the joint sizing exists.

### 4.3 Heat storage (`elements/thermal_storage/study.py`, `sizing.py`)

With the boiler fixed at its chosen size:

1. The year without storage gives the running cost $R_0$ (gas, levy, boiler variable O&M).
2. For each size $K$ (default 1, 2, 4, 8 and 12 hours of the boiler at full output, rounded up to 100 kWh), the year
   with storage gives $R_K$.
3. Value $V_K = R_0 - R_K - \text{fixed O\&M}_K$; investment $I_K$; payback $I_K / V_K$; lifetime profit
   $V_K \cdot \text{life} - I_K$; the same objectives as the battery.

Reasoning: with the boiler fixed, the tank can only save heat the boiler would release (when it runs for CO2) and
shift gas between days of different price. It cannot make the boiler smaller. This is the main limit of sizing one
at a time.

## 5. Joint sizing (sizing together)

`system/joint.py`, the default with two sized blocks or more (A16).

### 5.1 Formulation

The sizes $Q$ (boiler), $K$ (heat storage) and $B$ (battery) become variables of the dispatch of section 3 (PyPSA
capacity expansion), and the objective gets the yearly cost of the sizes:

$$
\min_{Q,K,B,\text{dispatch}} \; \text{dispatch cost (3.1)}
\;+\; \Big(\frac{c^{Q}}{L^{Q}} + o^{Q}\Big) Q
\;+\; \Big(\frac{c^{K}}{L^{K}} + o^{K}\Big) K
\;+\; \Big(\frac{c^{B}}{L^{B}} - a^{B}\Big) B
$$

- $c$: investment per unit of size (after subsidy for the battery), $L$: life in years, $o$: fixed O&M per unit and
  year, $a^B$: ancillary revenue per kWh of battery;
- the constraints of section 3 hold with the sizes as variables: $q^b_t \le Q$, $h_t \le K$,
  $q^{in}_t, q^{out}_t \le \rho K$, $e_t \le (1-r)wB$, $c^\pm_t \le (1-r)\kappa B$. The power limits follow the
  size through equality constraints on the links' capacities, so power is not a separate choice;
- when the boiler's size is free, the heat and CO2 demand have no slack: they must be met;
- a block with the objective custom keeps its size.

Reasoning: dividing each investment by its life (no discounting, A19) puts all blocks on the same yearly footing.
Minimising running costs + investment / life is the same rule as the studies' "highest lifetime profit" and "lowest
lifetime cost" (both are the yearly figure times the life), applied to all blocks at once. The difference with
section 4 is that the trade-offs between blocks are now inside the optimisation. Example: a heat storage that takes
the boiler's few highest hours of the year lets the boiler be smaller, and that saving is counted.

### 5.2 What is approximated, and how it is checked

The boiler and the heat storage are exact (their prices and O&M are linear in their size). The battery has rules that
are not linear in its size (A20):

- **price tiers and subsidy**: the price per kWh and the subsidy are taken at a reference size (the largest allowed),
  then the optimisation is repeated once at the size found if the linear terms differ there by more than 1 %;
- **usable share and reserve**: the same (exact in percent mode, approximate with a fixed reserve in kWh);
- **EMS costs**: a fixed yearly cost, hardware bought with any battery, and fees that are a share of the bill
  saving. They are not in the optimisation. After it, the battery is kept only if the site's yearly cost with these
  costs is still lower than without the battery; otherwise the system without battery is kept;
- **largest size**: the subsidised maximum (CH, with `cap_at_subsidy_size`), else the largest size of the battery's
  list, so the optimisation stays bounded;
- **one meter**: the limits of section 3.5 use the reference size's power (they apply only outside CH);
- **regime**: as in section 3.3, solved again with the DUP held in each regime when the result crosses the threshold.

### 5.3 Value of each block in the system

Each sized block is taken out once and the others are sized again without it:

$$ \text{Value}_X = \text{YearlyCost}(\text{best system without } X) - \text{YearlyCost}(\text{best system with } X) $$

This is the block's worth after its own investment per year, with the rest of the system adapting to its absence. The
boiler is not left out while it is the only heat source. With a battery, the EMS costs are counted the same way in
both systems.

### 5.4 After the joint sizing

Each block's study then runs at its joint size, for its own tables (the battery's bills, value split and payback; the
boiler's year). The heat storage's tab compares the system with it against the best system without it (section 5.3),
and splits its value into gas saved, carbon levy saved, boiler O&M saved, the smaller boiler's investment per year,
minus its own O&M.

Runtime: one joint optimisation takes about 2 minutes (a normal year about 25 s). The default HiGHS method is the
fastest of those tried (interior point was slower).

## 6. The electricity side (every run)

`system/electricity.py`. From the solved dispatch, each step is split (no optimisation):

| Flow | Formula |
|---|---|
| PV to load | $\min(PV_t, L_t)$, split between Voltiris and existing PV by $s_t$ |
| PV to battery | $\min(c^+_t, (PV_t - L_t)^+)$ |
| PV exported | $PV_t$ - PV to load - PV to battery |
| battery to load | $\min(c^-_t, (L_t - PV_t)^+)$ |
| battery to grid | $c^-_t$ - battery to load |
| grid to load | $L_t$ - PV to load - battery to load |
| grid to battery | $c^+_t$ - PV to battery |

so that the load, the PV, the import and the export all add up at every step.

**Self-consumption** $SC = \dfrac{\text{PV used on site}}{\text{PV produced}}$ and **self-sufficiency**
$SS = \dfrac{\text{PV used on site}}{\text{load}}$, where PV used on site is the PV to load plus the PV that goes
through the battery to the load, after the round-trip loss (the reference model's rule).

**Bill** = import cost + capacity charges - export revenue + EaaS fee. **Bill without PV**: the load all bought from
the grid in the starting regime. Their difference is what the PV (and the battery) save.

## 7. The site's yearly cost (every run)

`system/costs.py`. For the sizes chosen:

$$
\text{YearlyCost} = \underbrace{\text{Bill} + \text{gas} + \text{levy} + \text{O\&M}_{boiler} + \text{O\&M}_{storage} + \text{EMS} - A_B}_{\text{running}}
\;+\; \underbrace{\sum_{X} \frac{I_X}{L_X}}_{\text{investment per year}}
$$

over the Voltiris modules (direct sales; under EaaS the grower pays the fee instead), the boiler, the heat storage and
the battery with its EMS hardware. Existing PV is sunk. Unmet heat or CO2 is reported in quantities, not priced.
Dividing the battery's investment by its life stands for buying it again at the end of its life at full price (the
battery study's payback table counts replacements at a share of the price instead).

## 8. Comparing two scenarios

`system/scenarios.py`. Scenario A is the case as built; scenario B is the same case without some blocks. B can only
take blocks out: what cannot run without them goes too (a heat storage without a heat source, the gas supply without
a block that burns gas; the links in `common/blocks.json`). B is sized and run exactly like A. Then:

$$ \Delta = \text{YearlyCost}_B - \text{YearlyCost}_A \quad (\Delta > 0: \text{A is cheaper}) $$

$$ \text{Extra investment of A} = \sum I^{A} - \sum I^{B}, \qquad
\text{Running saving of A} = \text{running}_B - \text{running}_A, \qquad
\text{Payback} = \frac{\text{extra investment}}{\text{running saving}} $$

The payback is shown when A invests more and runs cheaper. Every line of the yearly cost and the key figures
(sizes, self-consumption, grid exchange, gas, CO2) are shown side by side.

## 9. Limits to keep in mind

- Perfect foresight: results are the best a system could do with a perfect forecast.
- No discounting of investments (A19, TO CHECK).
- Heat and electricity are not linked yet (no heat pump, CHP or electric heater), so today the joint sizing couples
  the boiler and the heat storage; the battery is sized in the same optimisation but nothing on the heat side
  affects it.
- No minimum load, start-up cost or part-load efficiency for the boiler; these would need integer variables.
- The heat and CO2 demand are inputs: the greenhouse's climate is not modelled, and the effect of the Voltiris
  modules on the demand is ignored (A12).
- Many prices and efficiencies are placeholders (TO CHECK in the parameter files).
