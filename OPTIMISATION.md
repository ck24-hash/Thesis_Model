# How the model optimises

This file explains every optimisation in the model: the yearly dispatch, each block's sizing study, the joint sizing,
and what is computed from their results (the electricity side, the site's yearly cost, each technology with and
without it). Each section gives the formulas, then why it is done that way. The code it describes is named at the start
of each section. Assumption IDs (A1 to A24) refer to `thesis.md` section 5.

Values written TO CHECK in the parameter files are placeholders, not sourced data.

## 1. The overall approach

Two kinds of decisions are taken:

- **Operation**: how each unit runs at every quarter hour of the year (grid import and export, battery charging,
  boiler and heat pump output, heat storage). For given sizes, this is one linear programme over the whole year.
- **Sizing**: the size of each sized block (battery in kWh, gas boiler and heat pump in kW of heat, heat storage in
  kWh of heat).
  The joint sizing makes the sizes variables of the same linear programme (section 5). After it only the operation is
  solved again: each block's year at its size, the system without each technology (section 8), and each size -10 %
  and +10 % (section 9). The results show the technical side first (sizes, how hard each block works, the year's
  energy), then the money.

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
| $c^+_t, c^-_t$ | battery charging (taken from the bus) and discharging (taken from the battery; $\eta^- c^-_t$ reaches the bus) | kW |
| $e_t$ | energy in the battery | kWh |
| $H_t$, $C_t$ | heat demand (kW) and CO2 demand (kg/h) of the greenhouse | |
| $g_t$ | gas burnt by the boiler | kW (of gas, lower heating value) |
| $q^{b}_t$ | boiler heat output | kW |
| $w_t$ | electricity drawn by the heat pump | kW |
| $COP_t$ | the heat pump's COP at $t$ (heat per kWh of electricity) | |
| $T^{out}_t$ | outside temperature | °C |
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
- CO2 bought at its price, $\sum_t p^{CO2}_t q^{CO2}_t \Delta t$, with an external CO2 supply (section 3.6);
- gas at its price plus the carbon levy $\lambda$ (per kg CO2) times the emission factor $\varepsilon$ (kg CO2 per
  kWh of gas), and the boiler's variable O&M $m^b$ per kWh of heat;
- unmet heat $u^H_t$ and unmet CO2 $u^C_t$ at penalties $\pi^H, \pi^C$ (10 per kWh and per kg). The penalties are
  solver devices, not prices (A15): they keep the year solvable when a unit is too small, and a size that needs them
  is reported as not covering the demand.

Fixed costs (investments, fixed O&M) do not depend on operation and are not in the dispatch. They enter the sizing.

### 3.2 Electricity bus

At every step, what enters the site's bus equals what leaves it:

$$ PV_t + I_t + \eta^- c^-_t = L_t + w_t + E_t + c^+_t $$

$w_t$ is the heat pump's electricity (0 without one): the heat pump is load like the greenhouse's, so the bills,
self-consumption and self-sufficiency count it.

The PV must run: Voltiris and existing PV are one generator whose output is fixed to their summed output
$PV_t = N \cdot y_t / 1000 + PV^{ex}_t$ ($N$ modules, $y_t$ the yield of one module in W). They share the one meter
of the site, as in the reference model, so they are one generator.

### 3.3 Grid

$$ 0 \le I_t \le \bar I, \qquad 0 \le E_t \le \bar E $$

$\bar I, \bar E$: the case's connection limits, else $2 \max_t L_t$ (with a heat pump $2 \max_t (L_t + H_t/COP_t)$,
its draw if it gave the whole heat demand) and $1.1 \max_t PV_t$.

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
   regime by the linear constraint $\Theta P_{Dec} - \sum_t I_t \Delta t \ge 0$ (A) or $\le 0$ (B), $\Theta$ the
   threshold and $P_{Dec}$ the year's billed peak, and keeps the cheaper.

### 3.4 Business model on the exports

The grower's value of an exported kWh:

- direct sales: $v_t$ = the feed-in (fixed, or the day-ahead price);
- EaaS (Voltiris owns the modules, the grower pays a price $p^{E}$ per MWh of Voltiris energy used on site): the
  grower's PV cash flow is $(1-s_t)\,FiT_t\,E_t - p^{E} s_t (PV_t - E_t)$, which equals
  $v_t E_t - p^{E} s_t PV_t$ with $v_t = (1-s_t) FiT_t + s_t\,p^{E}$. The last term does not depend on the dispatch,
  so the dispatch only needs $v_t$; the fee goes back into the bills.

Under EaaS the site exports at most its PV surplus ($E_t \le (PV_t - L_t)^+$) and imports nothing while it has one
(bounds on $I_t$ and $E_t$), since otherwise the solver would import cheap power and export Voltiris power at the
same moment. With a heat pump, the surplus $S_t$ goes to the heat pump first and the site imports only what it draws
beyond it: $I_t \le \max(1 - S_t / P^{hp}_t, 0)\, w_t$, with $w_t$ its draw and $P^{hp}_t = Q^{hp}/COP_t$ its largest
draw (time sharing within the quarter hour, as in section 3.9; a heat pump the surplus runs whole imports nothing).

### 3.5 Battery

For a bought size $B$ (kWh), with depth of discharge window $\Delta\theta = \theta^{max} - \theta^{min}$, C-rate
$\kappa$ and a reserve share $\psi$ kept for ancillary services (per country), the dispatch may use the energy
$E^B = (1-\psi)\,\Delta\theta\,B$ and the power $P^B = (1-\psi)\,\kappa B$:

$$ 0 \le e_t \le E^B, \qquad 0 \le c^+_t, c^-_t \le P^B $$

$$ e_t = (1-\sigma)^{\Delta t}\, e_{t-1} + \Delta t \big(\eta^{+} c^+_t - c^-_t\big), \qquad e_{0} = e_{|T|} \;\text{(cyclic)} $$

$\sigma$: self-discharge per hour (the daily value / 24), $\eta^+, \eta^-$: charge and discharge efficiencies.
The reserve is taken out of both the energy window and the power, so the dispatch only uses what is not sold to the
grid operator.

**One meter** (where cheating could pay: steps where exporting is worth more than importing, or with a negative
price; never in CH). A single meter cannot import and export at once, nor charge and discharge at once. Within a
quarter hour both may happen one after the other, so with shortfall $D_t = (L_t - PV_t)^+$, surplus
$S_t = (PV_t - L_t)^+$ and battery power $P^B$:

$$ c^+_t + c^-_t \le P^B, \qquad I_t \le D_t + \max(1 - S_t/P^B, 0)\,c^+_t, \qquad E_t \le S_t + \max(\eta^- - D_t/P^B, 0)\,c^-_t $$

(the export limit does not apply under EaaS, which has its own bounds). Where exporting is worth more than importing,
with or without a battery, also $I_t \le D_t + (P^B - S_t)^+$ and $E_t \le S_t + (\eta^- P^B - D_t)^+$ ($P^B = 0$
without one). With a heat pump, $I_t - w_t$ takes the place of $I_t$ in the import limits ($D_t, S_t$ use the
greenhouse load, A23).

These limits are exact for the step's averages (time sharing), and linear because $D_t, S_t$ are fixed numbers.

**PV-only export** (a contract that only pays for PV energy exported). The battery keeps an account $e^{PV}_t$ of
the PV energy it holds:

$$ 0 \le c^{PV}_t \le \min(S_t, c^+_t), \quad 0 \le d^{PV}_t \le c^-_t, \quad
e^{PV}_t = (1-\sigma)^{\Delta t} e^{PV}_{t-1} + \Delta t(\eta^+ c^{PV}_t - d^{PV}_t), \quad 0 \le e^{PV}_t \le e_t $$

$$ E_t \le S_t - c^{PV}_t + \eta^- d^{PV}_t $$

so grid energy stored in the battery serves the site but is never exported.

### 3.6 Heat side

Added when the system has a heat or CO2 source. Buses: heat (with a heat source), CO2 (with a CO2 source), gas
(with the boiler).

**Gas supply**: a generator on the gas bus, cost $p^{gas}_t + \lambda\varepsilon$ per kWh of gas.

**Gas boiler** of size $Q$ (kW of heat), efficiency $\eta^{b}$, usable share of the flue gas CO2 $\phi$:

$$ q^{b}_t = \eta^{b} g_t \le Q, \qquad \text{CO2 to the CO2 bus} = \varepsilon\,\phi\, g_t \;\text{(kg/h)} $$

**Heat pump** of size $Q^{hp}$ (kW of heat), on the outside air (no data center yet), supply temperature $T^{sup}$:

$$ q^{hp}_t = COP_t\, w_t, \qquad w_t \le \frac{Q^{hp}}{COP_t} \;\;(\text{so } q^{hp}_t \le Q^{hp}) $$

$$ COP_t = COP^{nom}\,\frac{T^{sup} - T^{ref}}{T^{sup} - T^{out}_t} \quad\text{(dynamic)}, \qquad COP_t = COP^{nom} \quad\text{(constant)} $$

The dynamic COP is a constant share of the Carnot COP $T^{sup}/(T^{sup}-T^{out}_t)$ (temperatures in K), scaled to
$COP^{nom}$ at the reference outside temperature $T^{ref}$ (A22). In PyPSA it is a link from the electricity bus to the
heat bus with a time-varying efficiency; its capacity is on the electricity side, $Q^{hp} / COP^{min}$
($COP^{min}$: the year's lowest COP), reduced at each step by $COP^{min}/COP_t$.

**Heat bus** at every step:

$$ q^{b}_t + q^{hp}_t + q^{out}_t + u^{H}_t = H_t + q^{in}_t + z^{H}_t $$

$z^H_t \ge 0$ is heat released (free): the boiler may give more heat than needed when it runs for CO2.

Which source gives the heat: the objective pays $(p^{gas}_t + \lambda\varepsilon)/\eta^{b} + m^b$ per kWh of heat from
the boiler and $c^{imp}_{t,r}/COP_t$ per kWh from the heat pump (plus the capacity charges its draw adds, or nothing
when PV covers it), so at every step the cheaper one runs, up to its size. When the boiler must run for the CO2
demand, its heat comes with the CO2 and the heat pump is used less.

**CO2 bus**, CO2 demand that must be met (`co2_mode: required`, A4):

$$ \varepsilon\,\phi\, g_t + q^{CO2}_t + u^{C}_t = C_t + z^{C}_t $$

$q^{CO2}_t \ge 0$ is CO2 bought (external CO2 supply), at its price $p^{CO2}_t$ per kg in the objective, at most the
supply's limit. At each step the solver therefore buys CO2 or burns gas for it, whichever costs less: burning gas
only for CO2 costs about $(p^{gas}_t + \lambda\varepsilon + m^b\eta^b) / (\varepsilon\phi)$ per kg, while the flue
gas CO2 comes free when the heat is needed anyway. With external CO2 the demand must be met; bought CO2 is not
counted in the site's emissions (A21). Without a boiler, all the CO2 is bought.

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
| dynamic | $\ell_{ref} \cdot \dfrac{T_{store} - T^{out}_t}{T_{store} - T^{K}_{ref}}$, at least 0 ($\ell_{ref}$: loss at the tank's reference outside temperature $T^{K}_{ref}$, $T_{store}$: mean tank temperature) |

The dynamic mode follows heat conduction through the tank walls, proportional to the temperature difference with the
outside, with a fixed mean tank temperature (the tank temperature does not follow the state of charge, which keeps
the loss linear in $h_t$).

## 4. The battery check: the reference sweep

`system/battery_check.py`, after the joint sizing when the run sizes the battery (`"system": {"battery_check": false}`
skips it, A26). The battery is sized again by the reference battery model's rule (`elements/battery/study.py`, the
same results as `elements/battery_reference` to the last digit), the other blocks at their joint sizes, and set
against the joint size:

1. The year without battery under the starting regime gives the baseline bill $\text{Bill}_0$.
2. For each size $B$ in the list (default 100 to 1,500 kWh in steps of 100, stopping at the subsidised maximum with
   CH's OCAN rule), the year with the battery gives $\text{Bill}_B$, with the regime handling of section 3.3.
3. Its value per year:

$$ V_B = \underbrace{(\text{Bill}_0 - \text{Bill}_B)}_{\text{bill saving}} + \underbrace{A_B}_{\text{ancillary revenue}} - \underbrace{\text{EMS}_B}_{\text{fixed + fees}} $$

   with $A_B = \text{rate} \cdot \psi\kappa B$ (the reserved power times the yearly rate per kW) and
   $\text{EMS}_B = \text{fixed} + f^{A} A_B + f^{S} \max(\text{Bill}_0 - \text{Bill}_B, 0)$.
4. Investment $I_B$ = battery price after subsidy + EMS hardware; payback $I_B / V_B$; lifetime profit
   $V_B \cdot \text{life} - I_B$.
5. Choice: **profit** (the highest lifetime profit among the sizes that pay back within the battery life, else the
   shortest payback) or **payback**.

The two rules differ: the joint sizing keeps the lowest yearly cost of the site, any size up to its limit, with the
battery and its replacements spread over the PV life; the sweep keeps the highest lifetime profit on its list, first
purchase only, over the battery life. They can pick different sizes even when both are right. The results set side by
side the size, yearly value, first purchase, payback, lifetime profit, battery per year over the PV life and the
site's yearly cost of both. On the Geneva example both give 2,495 kWh (the subsidised maximum).

The battery's own study at its joint size splits the bill saving into self-consumption (PV surplus stored instead of
exported), arbitrage (grid energy bought cheap, used dear), capacity charges saved and regime switch, so the value can
be explained.

## 5. Joint sizing (sizing together)

`system/joint.py`, every run (A16).

### 5.1 Formulation

The sizes $Q$ (boiler), $Q^{hp}$ (heat pump), $K$ (heat storage) and $B$ (battery) become variables of the dispatch of
section 3 (PyPSA capacity expansion), and the objective gets the yearly cost of the sizes:

$$
\min_{Q,Q^{hp},K,B,\text{dispatch}} \; \text{dispatch cost (3.1)}
\;+\; \Big(\frac{c^{Q}}{\tau^{Q}} + o^{Q}\Big) Q
\;+\; \Big(\frac{c^{hp}}{\tau^{hp}} + o^{hp}\Big) Q^{hp}
\;+\; \Big(\frac{c^{K}}{\tau^{K}} + o^{K}\Big) K
\;+\; \Big(\frac{c^{B}}{\tau^{B}} - a^{B}\Big) B
$$

- $c$: investment per unit of size (after subsidy for the battery), $\tau$: life in years, $o$: fixed O&M per unit
  and year, $a^B$: ancillary revenue per kWh of battery;
- the constraints of section 3 hold with the sizes as variables: $q^b_t \le Q$, $w_t \le Q^{hp}/COP_t$, $h_t \le K$,
  $q^{in}_t, q^{out}_t \le \rho K$, $e_t \le (1-\psi)\Delta\theta B$, $c^\pm_t \le (1-\psi)\kappa B$. The power limits follow the
  size through equality constraints on the links' capacities, so power is not a separate choice;
- when a heat source's size is free (boiler or heat pump), the heat demand has no slack, and when the boiler's is
  free the CO2 demand has none either: they must be met;
- a block with the objective custom keeps its size (0: not installed).

Reasoning: dividing each investment by its life (no discounting, A19) puts all blocks on the same yearly footing.
Minimising running costs + investment / life is the same rule as the studies' "highest lifetime profit" and "lowest
lifetime cost" (both are the yearly figure times the life), applied to all blocks at once, so the trade-offs between
blocks are inside the optimisation. Example: a boiler alone that must meet the demand comes out at the size of the
demand's busiest step, $Q^{need} = \max_t \max(H_t, C_t\,\eta^{b}/(\varepsilon\phi))$ (the CO2 term when the CO2
demand must be met and none is bought); all larger sizes burn about the same gas. Only something that takes its peaks
makes it smaller: a heat storage that takes the boiler's few highest hours of the year, or a heat pump, and that
saving is counted.

### 5.2 What is approximated, and how it is checked

The boiler, the heat pump and the heat storage are exact (their prices and O&M are linear in their size). The battery has rules that
are not linear in its size (A20):

- **price tiers and subsidy**: the price per kWh and the subsidy are taken at a reference size (the largest allowed),
  then the optimisation is repeated once at the size found if the linear terms differ there by more than 1 %;
- **usable share and reserve**: the same (exact in percent mode, approximate with a fixed reserve in kWh);
- **EMS costs**: a fixed yearly cost, hardware bought with any battery, and fees that are a share of the bill
  saving. They are not in the optimisation. After it, the battery is kept only if the site's yearly cost with these
  costs is still lower than without the battery; otherwise the system without battery is kept;
- **largest size**: the subsidised maximum (CH, with `cap_at_subsidy_size`), else the largest size of the battery's
  list, so the optimisation stays bounded;
- **one meter**: the limits of section 3.5 use the reference size's power (they apply only outside CH); where they
  apply, the optimisation is also repeated once at the size found when it is more than 5 % from the reference size;
- **regime**: as in section 3.3, solved again with the DUP held in each regime when the result crosses the threshold
  (with a battery or a heat pump: both change what is drawn from the grid).

### 5.3 The battery's EMS check

With a battery, the best system without it is optimised too. The battery is kept only if the site's yearly cost with
its EMS costs (a share of its bill saving) is still lower than without it. What every block is worth to the site is
in section 8.

Why it is not in the optimisation: the fixed EMS cost and the hardware are paid in full with any battery and are 0
without one, which needs a yes/no variable (a MILP, much slower), and the fee on the saving needs the bill without
battery, the result of another solve.

In the systems without a technology (section 8) the check is shorter, since it would otherwise double each of them:

1. When the battery sits at its limit, the solve also gives the value of one more kWh of limit (its shadow price).
   The site's cost falls less and less with each kWh added in a linear programme, so the battery's whole saving
   beyond its own cost is at least its usable kWh times that value. If that already covers its EMS costs (fixed
   cost, fee on the reserve revenue, hardware over the PV life), it is kept and nothing more is solved. Used when
   there is no fee on the bill saving and the regime is the starting one with no DUP held (and without a heat pump
   in CH, whose draw can move the regime without battery).
2. Otherwise one year without the battery is solved with the other sizes kept as found with it (about 25 s instead
   of a joint sizing). That system costs at least as much as the best one without battery, so a battery that does
   not pay against it is left out (and the system without it sized again). One that pays against it is kept: the
   approximation is that the other sizes are not sized again without the battery, which matters only for a battery
   that barely pays.

### 5.4 After the joint sizing

Each block's year is then solved at its joint size, for its own tables (the battery's bills, value split and payback; the
boiler's year; the heat pump's year: heat given, electricity drawn, SPF, cost per MWh of heat). The heat storage's tab
compares the system with it against the best system without it (section 8) and splits its value line by line of the
site's yearly cost (gas, carbon levy, boiler O&M, the grid bill when it shifts the heat pump's electricity, the smaller
heat sources' investment per year), minus its own O&M.

With a heat pump the heat side depends on the electricity side, so the battery's own study counts it: a size's value
is its bill saving + the gas and CO2 bought it saves by changing when the heat pump runs (against the year without
battery) + ancillary revenue - EMS costs.

The technical summary (`system/technical.py`) then gives, for each piece of equipment, its size, how it was found,
the yearly cost of one more unit of size ($c/\tau + o$ per kW or kWh; the battery's per kWh bought over the PV life,
less its reserve revenue), the energy it gives and its share of the demand, its full-load hours (cycles for storage)
and its hours at full size (at least 99 % of the size), and the year's energy flows. Why the hours at full size
explain a size: the solver adds capacity while one more unit saves more per year than its yearly cost, and the last
unit is used only in the hours the block runs at full size. Few such hours mean a size set by a peak.

Runtime: one joint optimisation takes about 2 minutes (a normal year about 25 s). The default HiGHS method is the
fastest of those tried (interior point was slower).

## 6. The electricity side (every run)

`system/electricity.py`. From the solved dispatch, each step is split (no optimisation), with the battery's net power
at the bus $\nu_t = \eta^- c^-_t - c^+_t$, its discharging $\nu^+_t = \max(\nu_t, 0)$ and charging
$\nu^-_t = \max(-\nu_t, 0)$. With a heat pump, $L_t$ in this section is the site's load $L_t + w_t$.

| Flow | Formula |
|---|---|
| PV to load, $PV^{load}_t$ | $\min(PV_t, L_t)$, split between Voltiris and existing PV by $s_t$ |
| PV to battery, $\nu^{PV}_t$ | $\min(\nu^-_t, (PV_t - L_t)^+)$ |
| PV exported | $PV_t$ - PV to load - PV to battery |
| battery to load, $\nu^{load}_t$ | $\min(\nu^+_t, (L_t - PV_t)^+)$ |
| battery to grid | $\nu^+_t$ - battery to load |
| grid to load | $L_t$ - PV to load - battery to load |
| grid to battery, $\nu^{grid}_t$ | $\nu^-_t$ - PV to battery |

so that the load, the PV, the import and the export all add up at every step.

**Self-consumption** $SC = \dfrac{\text{PV used on site}}{\text{PV produced}}$ and **self-sufficiency**
$SS = \dfrac{\text{PV used on site}}{\text{load}}$, where PV used on site is the PV to load plus the PV that goes
through the battery to the load, after the round-trip loss (the reference model's rule).

**Bill** = import cost + capacity charges - export revenue + EaaS fee. **Bill without PV**: the load all bought from
the grid in the starting regime. Their difference is what the PV (and the battery) save.

### 6.1 Savings against the other way of supplying each flow

Each storage or supply is set against what the site would otherwise do for the same flow. The parts add up exactly
to the difference between the two years.

- **PV**, against buying all the load (the year without battery, same regime):
  $\sum_t PV^{load}_t c^{imp}_t \Delta t$ (imports avoided) + export revenue + capacity charges saved - EaaS fee
  = bill without PV - bill.
- **Battery**, against the same system without it:
  $\sum_t \nu^{load}_t c^{imp}_t \Delta t$ (imports avoided) + its exports
  $-\sum_t \nu^{PV}_t FiT_t \Delta t$ (PV stored instead of exported; under EaaS only the existing PV's share
  $1 - s_t$ of the feed-in, as for its exports)
  $-\sum_t \nu^{grid}_t c^{imp}_t \Delta t$ (grid energy bought to charge) + capacity charges saved + other (regime
  switch, EaaS fee) = bill without battery - bill with it. Ancillary revenue and EMS costs come on top (section 4).
  The exact match holds because the PV and the greenhouse load are fixed: without a battery the site imports exactly
  $(L_t - PV_t)^+$ and exports $(PV_t - L_t)^+$. With a heat pump its draw changes with the battery, and that change
  is in other too.
- **Heat storage**, against the system without it:
  gas its heat replaces = $\sum_t q^{out}_t / \eta^b$, at the gas price and levy of the moment it is given back;
  extra gas burnt to fill it = gas replaced - gas saved; gas saved = gas without storage - gas with it. Heat that
  would be released anyway (when the boiler runs for CO2) fills it for free.
- **Bought CO2**, against burning gas only for it:
  $\sum_t q^{CO2}_t \, \dfrac{p^{gas}_t + \lambda\varepsilon + m^b\eta^b}{\varepsilon\phi} \Delta t$ (what burning
  gas would cost, its heat not needed) minus what was paid. With a heat storage, part of that heat could have been
  stored, so the real saving is a little lower.

### 6.2 Does the model weigh a storage against the other ways of supplying the flow?

Yes, at two levels.

**Operation, at every quarter hour.** The dispatch has every option at once and minimises the year's cost, so it
uses the battery only when the electricity it gives back (after its losses) is worth more than its cost at charging
time: PV that could have been exported, or grid power bought cheaper. The same goes for the heat storage (its heat
against gas burnt at that moment) and for bought CO2 (its price against burning gas for it). Because it sees the
whole year at once, it also weighs effects that span several hours, such as a battery shaving a monthly peak.

**Sizing.** In the joint sizing (section 5) a storage's size is a variable whose yearly cost (investment ÷ life + fixed
O&M) is in the same objective as the running costs it saves. The solver therefore grows it until one more kWh of
storage would save less per year than it costs per year. At that point the last kWh just pays for itself, and the
storage as a whole saves more than it costs. It also counts what the storage saves on other blocks, for example a
smaller boiler. The battery check (section 4) makes the same comparison on a list of battery sizes: each size's year
is optimised, its yearly saving against the system without it is set against its investment, and the objective
(lifetime profit, payback) picks one.

What it does not weigh: the external CO2 supply and Voltiris are not sized (the CO2 supply's fixed cost and the
module count are given). Their value is shown with and without them (section 8).

## 7. The site's yearly cost (every run)

`system/costs.py`. For the sizes chosen:

$$
\text{YearlyCost} = \underbrace{\text{Bill} + \text{gas} + \text{levy} + \text{O\&M}_{boiler} + \text{O\&M}_{heat\,pump} + \text{O\&M}_{storage} + \text{CO2 bought} + \text{CO2 fixed} + \text{EMS} - A_B}_{\text{running}}
\;+\; \underbrace{\sum_{X} \frac{I_X}{\tau_X}}_{\text{investment per year}}
$$

(CO2 fixed: the external CO2 supply's fixed cost per year.)

over the Voltiris modules (direct sales; under EaaS the grower pays the fee instead), the boiler, the heat pump, the
heat storage and the battery with its EMS hardware. The heat pump's electricity is in the bill. Existing PV is sunk. Unmet heat or CO2 is reported in quantities, not priced.
The battery is spread over the PV life as its payback table counts it: the first purchase after subsidy with the EMS
hardware, plus the replacements within the PV life at a share of the gross price (unsubsidised), divided by the PV
life. The joint sizing uses the same cost per kWh (without the EMS hardware).

## 8. With and without each technology

`system/effects.py`, every run. For each block $X$ the system could do without (not the greenhouse or the grid, not
the gas supply, which follows the boiler), the system without $X$ is sized again together (section 5) and set against
the system with it. What cannot run without $X$ goes too (a heat storage without a heat source; the links in `common/blocks.json`).
$X$ is not evaluated when leaving it out would leave the heat or CO2 demand without a source (the gas boiler or the
heat pump while it is the only heat source, the gas boiler or the external CO2 while it is the only CO2 source): that
system would not model the demand and look cheaper than it is.

Both systems are counted the same way (section 7, from the optimised year). A system without $X$ that keeps a battery
checks that it pays for its EMS costs (section 5.3, the shorter check); a battery that does not pay for them is left
out there too. Then:

$$ \Delta_X = \text{YearlyCost}(\text{without } X) - \text{YearlyCost}(\text{with } X) \quad (\Delta_X > 0: X \text{ lowers the yearly cost}) $$

$$ \text{Extra investment} = \sum I^{with} - \sum I^{without}, \qquad
\text{Running saving} = \text{running}^{without} - \text{running}^{with}, \qquad
\text{Payback} = \frac{\text{extra investment}}{\text{running saving}} $$

Each line of the yearly cost changes by (with $-$ without): below 0 the technology lowers it. The key figures (sizes,
PV, self-consumption, self-sufficiency, grid exchange, gas, CO2 emitted and bought, unmet demand) have a direction:
lower is better for the grid import, gas and CO2 emitted, higher for self-consumption and self-sufficiency. Each
technology's tab shows a verdict, its advantages and disadvantages, and the yearly cost from without to with it, one
bar per line that changes; the System tab lists every technology, first what it changes technically (grid import,
self-sufficiency, gas, CO2 emitted, unmet demand), then what it is worth.

## 9. How much the sizes matter (sensitivity)

`system/sensitivity.py`, after the sizing (`"system": {"sensitivity": false}` skips it, A25). Each installed sized
block, and the Voltiris modules, at its size $\times 0.9$ and $\times 1.1$, everything else at its chosen size. Only
the year's operation (section 3) is solved again: no new sizing, under the joint sizing's regime, the battery's EMS
costs from the joint sizing's bill without battery. Each row gives the site's yearly cost, its change against the
year at the chosen sizes, and the grid import, self-sufficiency, gas, CO2 emitted and unmet heat and CO2. That is
$1 + 2n$ years for $n$ pieces of equipment.

Reading it: a size at the optimum costs more both ways. A size that is cheaper at +10 % sits at a limit of the sizing
(the battery's subsidised maximum or the largest size of its list). Unmet heat or CO2 is not priced: a smaller size
that leaves demand unmet looks cheaper but does not do the job. On the Geneva example the battery at -10 % and +10 %
raises the yearly cost by 1,519 and 1,475 CHF; the Voltiris modules change it by +931 and -931 CHF.

## 10. Limits to keep in mind

- Perfect foresight: results are the best a system could do with a perfect forecast.
- No discounting of investments (A19, TO CHECK).
- The heat pump links heat and electricity; the CHP and the electric backup heater are not built yet. Some rules
  fixed before the solve see the greenhouse load only, not the heat pump's draw (A23).
- The heat pump's size holds at any outside temperature, it has no minimum part load, and its source is the outside
  air only (no data center yet) (A22).
- No minimum load, start-up cost or part-load efficiency for the boiler; these would need integer variables.
- The heat and CO2 demand are inputs: the greenhouse's climate is not modelled, and the effect of the Voltiris
  modules on the demand is ignored (A12).
- Many prices and efficiencies are placeholders (TO CHECK in the parameter files).
