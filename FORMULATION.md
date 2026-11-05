# Mathematical formulation of the model

One year at a 15-minute step, written as a linear programme. Section 5 is the yearly operation for given sizes. Section
7 makes the sizes variables (joint sizing). Section 8 sizes one block at a time. Sections 9 and 10 are what is computed
from the solved year.

---

## 1. Sets and indices

| Symbol | Meaning |
|---|---|
| $t \in \mathcal{T} = \{1,\dots,N\}$ | time steps of the year, $N = 35\,040$ |
| $\Delta t = 0.25$ h | length of a step |
| $m \in \{1,\dots,12\}$, $\mathcal{T}_m$ | months, and the steps of month $m$ |
| $\mathcal{T}^{W}$ | steps inside a tariff window $W$ (peak, off-peak, all) |
| $k \in \{1,\dots,\bar k\}$, $\mathcal{T}_k$ | time slots of a staircase capacity charge (FR TURPE), and their steps |
| $r \in \mathcal{R}$ | tariff regime (CH SIG: A, B) |
| $\mathcal{T}^{>}$ | steps where exporting is worth more than importing: $v_t > \pi_{t,r}$ (not under EaaS) |
| $\mathcal{T}^{<0}$ | steps with a negative import or export price |
| $\mathcal{T}^{1m} = \mathcal{T}^{>} \cup \mathcal{T}^{<0}$ | steps where the one-meter rules apply |

## 2. Input data (time series, one value per step)

| Symbol | Meaning | Unit |
|---|---|---|
| $L_t$ | electricity load of the greenhouse | kW |
| $H_t$ | heat demand of the greenhouse | kW |
| $C_t$ | CO2 demand of the greenhouse | kg/h |
| $y_t$ | yield of one Voltiris module | W |
| $PV^{X}_t$ | output of the existing PV | kW |
| $\pi^{DA}_t$ | day-ahead electricity price (NL, FR tariffs) | per kWh |
| $p^{g}_t$ | gas price (lower heating value) | per kWh of gas |
| $p^{CO2}_t$ | price of bought CO2 | per kg |
| $T^{out}_t$ | outside temperature (dynamic heat loss, dynamic heat pump COP) | °C |

Data coarser than 15 minutes (a regular step of whole quarter hours, such as hourly or daily) is brought to
$\Delta t$: kW, kg/h, prices and temperatures are repeated in each step, kWh per step are divided. Prices given in EUR are multiplied by the exchange rate into the market's currency.

## 3. Parameters

### 3.1 PV and business model

| Symbol | Meaning | Unit |
|---|---|---|
| $n$ | number of Voltiris modules | |
| $PV_t = n\,y_t/1000 + PV^{X}_t$ | PV output on site (must run) | kW |
| $\sigma_t = n\,y_t / (1000\,PV_t)$ | Voltiris share of the PV at $t$ (0 when $PV_t = 0$) | |
| $\varphi_t$ | feed-in tariff (fixed, or the day-ahead price) | per kWh |
| $p^{E}$ | EaaS price paid to Voltiris per kWh of Voltiris energy used on site | per kWh |
| $\mathbb{1}^{E}$ | 1 under EaaS with modules installed, else 0 | |

### 3.2 Grid

| Symbol | Meaning | Unit |
|---|---|---|
| $\pi_{t,r}$ | import price under regime $r$ (sum of the tariff's energy and network components) | per kWh |
| $v_t$ | value of 1 kWh exported for the grower (section 5) | per kWh |
| $\bar I, \bar E$ | import and export limits of the connection | kW |
| $\omega^{M}_{r}, \omega^{Y}_{r}$ | monthly and yearly peak charge rates | per kW and month / year |
| $b_{k,r}$ | staircase rate of slot $k$, with $b_{\bar k+1,r} = 0$ | per kW and year |
| $\Theta$ | DUP threshold between the two regimes (SIG: 3,000 h) | h |
| $D_t = (L_t - PV_t)^+$ | shortfall without battery | kW |
| $S_t = (PV_t - L_t)^+$ | surplus without battery | kW |

### 3.3 Battery

| Symbol | Meaning | Unit |
|---|---|---|
| $\kappa$ | C-rate: power per kWh bought | 1/h |
| $\theta^{min}, \theta^{max}$, $\Delta\theta = \theta^{max} - \theta^{min}$ | lowest and highest state of charge, usable window | share |
| $\psi$ | share of the window and of the power kept as ancillary reserve | |
| $\eta^{+}, \eta^{-}$ | charge and discharge efficiency | |
| $\delta$ | self-discharge per hour | share per h |
| $E^{B} = (1-\psi)\,\Delta\theta\,B$ | energy the dispatch may use, for $B$ kWh bought | kWh |
| $P^{B} = (1-\psi)\,\kappa\,B$ | power the dispatch may use | kW |
| $a$ | ancillary revenue per reserved kW and year | per kW and year |
| $p^{B}(B)$ | battery price per kWh, linear between price tiers | per kWh |
| $\tau^{B}$ | battery life | years |
| $F^{EMS}, C^{EMS}$ | EMS fixed cost per year, EMS hardware | money |
| $f^{A}, f^{S}$ | EMS fees: share of the ancillary revenue, share of the bill saving | |

### 3.4 Gas, boiler, heat pump, heat storage, external CO2

| Symbol | Meaning | Unit |
|---|---|---|
| $\varepsilon$ | emission factor of natural gas | kg CO2 per kWh of gas |
| $\lambda$ | carbon levy | per kg CO2 |
| $\eta^{G}$ | boiler efficiency | kWh heat per kWh gas |
| $\phi$ | usable share of the flue gas CO2 | |
| $m^{G}$ | boiler variable O&M | per kWh of heat |
| $COP^{nom}$ | heat pump COP at the reference outside temperature (constant mode: all year) | kWh heat per kWh electricity |
| $T^{sup}, T^{ref}$ | heat pump supply temperature (60), reference outside temperature | °C |
| $COP_t$ | heat pump COP at $t$ (constraint 5.8b); $COP^{min} = \min_t COP_t$ | |
| $\eta^{in}, \eta^{out}$ | heat storage charge and discharge efficiency | |
| $\rho$ | heat storage power per kWh of size | 1/h |
| $\ell_t$ | heat storage loss per hour (section 5, constraint 5.12) | share per h |
| $\bar b$ | most CO2 the external supply delivers (else the CO2 demand's peak) | kg/h |
| $\mu^{H}, \mu^{C}$ | penalties for unmet heat and CO2 (solver devices) | per kWh, per kg |

### 3.5 Investment and fixed costs

| Symbol | Meaning | Unit |
|---|---|---|
| $c^{Q}, o^{Q}, \tau^{Q}$ | boiler price, fixed O&M per year, life | per kW of heat, years |
| $c^{hp}, o^{hp}, \tau^{hp}$ | heat pump price, fixed O&M per year, life | per kW of heat, years |
| $c^{K}, o^{K}, \tau^{K}$ | heat storage price, fixed O&M per year, life | per kWh, years |
| $F^{CO2}$ | external CO2 fixed cost per year | money |
| $c^{PV}, \tau^{PV}$ | Voltiris price per Wp, PV life | |
| $f^{sub}, T^{sub}$ | battery subsidy share, subsidised maximum size | , kWh |

---

## 4. Decision variables

### 4.1 Operation (one per step, all $\ge 0$)

| Symbol | Meaning | Unit |
|---|---|---|
| $I_t, E_t$ | grid import, grid export | kW |
| $x^{+}_t$ | battery charging, taken from the bus | kW |
| $x^{-}_t$ | battery discharging, taken from the battery ($\eta^{-}x^{-}_t$ reaches the bus) | kW |
| $e_t$ | energy in the battery | kWh |
| $g_t$ | gas burnt by the boiler | kW of gas |
| $w_t$ | electricity drawn by the heat pump (it gives $COP_t\,w_t$ of heat) | kW |
| $z^{H}_t$ | heat released (not used) | kW |
| $s^{+}_t$ | heat into the storage, taken from the heat bus | kW |
| $s^{-}_t$ | heat out of the storage ($\eta^{out}s^{-}_t$ reaches the heat bus) | kW |
| $h_t$ | heat in the storage | kWh |
| $q^{CO2}_t$ | CO2 bought | kg/h |
| $z^{C}_t$ | CO2 vented | kg/h |
| $u^{H}_t, u^{C}_t$ | unmet heat, unmet CO2 (only when the sizes are fixed) | kW, kg/h |

### 4.2 Tariff variables

| Symbol | Meaning | Unit |
|---|---|---|
| $P^{M}_m$ | billed peak of month $m$ (monthly peak charge) | kW |
| $P^{Y}$ | billed peak of the year (yearly peak charge) | kW |
| $P_k$ | billed peak of staircase slot $k$ | kW |
| $x^{+,PV}_t$, $x^{-,PV}_t$, $e^{PV}_t$ | battery charging from the PV surplus, discharging of PV energy, PV energy held (PV-only battery export) | kW, kW, kWh |

### 4.3 Sizes

| Symbol | Meaning | Unit |
|---|---|---|
| $Q$ | gas boiler, heat output | kW |
| $Q^{hp}$ | heat pump, heat output | kW |
| $K$ | heat storage | kWh of heat |
| $B$ | battery, energy bought | kWh |

Fixed numbers in sections 5 and 8; variables in section 7.

---

## 5. Yearly operation for given sizes

### Objective

$$
\min \;\; \underbrace{\sum_{t} \big(\pi_{t,r}\,I_t - v_t\,E_t\big)\Delta t}_{\text{grid energy}}
\;+\; \underbrace{\mathrm{CC}_r}_{\text{capacity charges}}
\;+\; \underbrace{\sum_{t} \big(p^{g}_t + \lambda\varepsilon\big)\,g_t\,\Delta t}_{\text{gas and levy}}
\;+\; \underbrace{\sum_{t} m^{G}\eta^{G} g_t\,\Delta t}_{\text{boiler O\&M}}
\;+\; \underbrace{\sum_{t} p^{CO2}_t\,q^{CO2}_t\,\Delta t}_{\text{CO2 bought}}
\;+\; \underbrace{\sum_{t} \big(\mu^{H} u^{H}_t + \mu^{C} u^{C}_t\big)\Delta t}_{\text{unmet demand}}
$$

with the capacity charges

$$
\mathrm{CC}_r = \omega^{M}_r \sum_{m} P^{M}_m \;+\; \omega^{Y}_r\, P^{Y} \;+\; \sum_{k=1}^{\bar k} \big(b_{k,r} - b_{k+1,r}\big)\, P_k
$$

and the export value

$$
v_t = \begin{cases} \varphi_t & \text{direct sales} \\ (1-\sigma_t)\,\varphi_t + \sigma_t\,p^{E} & \text{EaaS} \end{cases}
$$

### Constraints

**5.1 Electricity bus**, for all $t$:

$$ PV_t + I_t + \eta^{-} x^{-}_t = L_t + w_t + E_t + x^{+}_t $$

**5.2 Grid connection**, for all $t$:

$$ 0 \le I_t \le \bar I, \qquad 0 \le E_t \le \bar E $$

Under EaaS:

$$ E_t \le S_t, \qquad I_t = 0 \;\text{ when } S_t > 0 $$

(the site exports at most its PV surplus over the greenhouse load, and buys nothing while it has one). With a heat
pump, the second rule becomes

$$ I_t \le \Big(1 - \frac{S_t}{Q^{hp}/COP_t}\Big)^+ w_t \quad \text{when } S_t > 0 $$

(the surplus runs the heat pump first; the site imports only what it draws beyond it, time sharing within the step;
in the joint sizing $Q^{hp}$ here is the fixed size, else the heat demand's peak).

**5.3 Capacity charges**

$$ P^{M}_m \ge I_t \quad \forall\, t \in \mathcal{T}_m \cap \mathcal{T}^{W}, \qquad P^{M}_m \ge P^{M}_{m-1} \;\text{ (annual ratchet only)} $$

$$ P^{Y} \ge I_t \quad \forall\, t \in \mathcal{T}^{W} $$

$$ P_k \ge I_t \quad \forall\, t \in \mathcal{T}_k, \qquad P_k \ge P_{k-1} $$

**5.4 Regime lock** (when the DUP must stay in regime $r$):

$$ \text{A:}\;\; \Theta\, P^{M}_{12} \ge \sum_t I_t\,\Delta t \qquad\qquad \text{B:}\;\; \sum_t I_t\,\Delta t \ge \Theta\, P^{M}_{12} $$

**5.5 Battery**, for all $t$ (cyclic: $e_0 = e_N$):

$$ e_t = (1-\delta)^{\Delta t}\, e_{t-1} + \Delta t\,\big(\eta^{+} x^{+}_t - x^{-}_t\big) $$

$$ 0 \le e_t \le E^{B}, \qquad 0 \le x^{+}_t \le P^{B}, \qquad 0 \le x^{-}_t \le P^{B} $$

**5.6 One meter**, for $t \in \mathcal{T}^{>}$:

$$ I_t - w_t \le D_t + \big(P^{B} - S_t\big)^+, \qquad E_t \le S_t + \big(\eta^{-}P^{B} - D_t\big)^+ \qquad (P^{B} = 0 \text{ without a battery}) $$

and with a battery, for $t \in \mathcal{T}^{1m}$:

$$ x^{+}_t + x^{-}_t \le P^{B} $$

$$ I_t - \alpha_t\, x^{+}_t - w_t \le D_t, \qquad \alpha_t = \Big(1 - \frac{S_t}{P^{B}}\Big)^+ $$

($D_t, S_t$: shortfall and surplus of the greenhouse load against the PV; the heat pump's draw $w_t$ is a variable,
added to what may be imported.)

$$ E_t - \beta_t\, x^{-}_t \le S_t, \qquad \beta_t = \Big(\eta^{-} - \frac{D_t}{P^{B}}\Big)^+ \quad \text{(not under EaaS)} $$

**5.7 PV-only battery export** (when the contract pays only for PV energy exported), for all $t$
($e^{PV}_0 = e^{PV}_N$):

$$ 0 \le x^{+,PV}_t \le \min\big(S_t,\; x^{+}_t\big), \qquad 0 \le x^{-,PV}_t \le x^{-}_t $$

$$ e^{PV}_t = (1-\delta)^{\Delta t}\, e^{PV}_{t-1} + \Delta t\,\big(\eta^{+} x^{+,PV}_t - x^{-,PV}_t\big), \qquad 0 \le e^{PV}_t \le e_t $$

$$ E_t \le S_t - x^{+,PV}_t + \eta^{-} x^{-,PV}_t $$

**5.8 Gas boiler**, for all $t$:

$$ \eta^{G}\, g_t \le Q $$

**5.8b Heat pump**, for all $t$:

$$ 0 \le w_t \le \frac{Q^{hp}}{COP_t} \qquad (\text{so } COP_t\,w_t \le Q^{hp}) $$

$$ COP_t = COP^{nom}\,\frac{T^{sup} - T^{ref}}{T^{sup} - T^{out}_t} \qquad\text{(dynamic)}, \qquad COP_t = COP^{nom} \qquad\text{(constant)} $$

The dynamic COP is a constant share of the Carnot COP: $COP_t = \eta^{C}\,\frac{T^{sup}}{T^{sup} - T^{out}_t}$ (in K)
with $\eta^{C} = COP^{nom}\,(T^{sup} - T^{ref})/T^{sup}$.

**5.9 Heat bus**, for all $t$:

$$ \eta^{G} g_t + COP_t\,w_t + \eta^{out} s^{-}_t + u^{H}_t = H_t + s^{+}_t + z^{H}_t $$

**5.10 Heat storage**, for all $t$ (cyclic: $h_0 = h_N$):

$$ h_t = (1-\ell_t)^{\Delta t}\, h_{t-1} + \Delta t\,\big(\eta^{in} s^{+}_t - s^{-}_t\big) $$

$$ 0 \le h_t \le K, \qquad 0 \le s^{+}_t \le \rho K, \qquad 0 \le \eta^{out} s^{-}_t \le \rho K $$

**5.11 CO2 bus**, for all $t$, CO2 demand that must be met (always with external CO2):

$$ \varepsilon\,\phi\, g_t + q^{CO2}_t + u^{C}_t = C_t + z^{C}_t, \qquad 0 \le q^{CO2}_t \le \bar b $$

CO2 as a by-product (no external CO2): $\varepsilon\phi g_t = z^{C}_t$ in the optimisation, and afterwards the
greenhouse takes $\min(\varepsilon\phi g_t,\, C_t)$.

**5.12 Heat storage loss per hour**, one of:

$$ \ell_t = \ell \qquad\text{(constant)} $$

$$ \ell_t = \ell_{\,season(t)}, \quad season \in \{\text{winter (Dec-Feb)}, \text{spring (Mar-May)}, \text{summer (Jun-Aug)}, \text{autumn (Sep-Nov)}\} \qquad\text{(seasonal)} $$

$$ \ell_t = \max\!\Big(0,\; \ell_{ref}\,\frac{T_{store} - T^{out}_t}{T_{store} - T^{K}_{ref}}\Big) \qquad\text{(dynamic)} $$

where $\ell_{ref}$ is the loss at the tank's reference outside temperature $T^{K}_{ref}$, and $T_{store}$ the mean tank
temperature.

**5.13 Domains**

$$ I_t, E_t, x^{\pm}_t, e_t, g_t, w_t, z^{H}_t, s^{\pm}_t, h_t, q^{CO2}_t, z^{C}_t, u^{H}_t, u^{C}_t, P^{M}_m, P^{Y}, P_k \ge 0 $$

A block absent from the system has its variables fixed to 0.

---

## 6. Regime

Hours of use (DUP) of an import profile $I$, and the regime it falls under:

$$ \mathrm{DUP}(I) = \frac{\sum_t I_t\,\Delta t}{\max_{t \in \mathcal{T}^{peak}} I_t}, \qquad
r(I) = \begin{cases} \text{A} & \mathrm{DUP}(I) \le \Theta \\ \text{B} & \mathrm{DUP}(I) > \Theta \end{cases} $$

Starting regime: $r_0 = r(D)$, the site without battery (or the regime the case fixes). A solution under $r_0$ whose
$\mathrm{DUP}(I^*)$ falls in the other regime $r_1$ is solved again under $(r_0, \text{lock } r_0)$ and
$(r_1, \text{lock } r_1)$ (constraint 5.4), and the cheaper is kept.

---

## 7. Joint sizing (sizes as variables)

### Objective

$$
\min_{Q,\,Q^{hp},\,K,\,B,\;\text{operation}} \;\; \text{objective of section 5 (without } u^{H}, u^{C}\text{)}
\;+\; \Gamma^{Q} Q \;+\; \Gamma^{hp} Q^{hp} \;+\; \Gamma^{K} K \;+\; \Gamma^{B} B
$$

with the yearly cost of one unit of size

$$ \Gamma^{Q} = \frac{c^{Q}}{\tau^{Q}} + o^{Q}, \qquad
\Gamma^{hp} = \frac{c^{hp}}{\tau^{hp}} + o^{hp}, \qquad
\Gamma^{K} = \frac{c^{K}}{\tau^{K}} + o^{K}, \qquad
\Gamma^{B} = \frac{\hat c^{B}}{\tau^{PV}} - \hat a^{B} $$

with $\mathrm{Repl}(B) = \max\big(\tau^{PV}/\tau^{B} - 1,\ 0\big)\, f^{repl}\, \mathrm{GrossPrice}(B)$ the battery's
replacements within the PV life (unsubsidised).

### Constraints

All constraints of section 5, with $Q, Q^{hp}, K, B \ge 0$ as variables (a size given in the case stays fixed) and

$$ u^{H}_t = 0 \text{ when } Q \text{ or } Q^{hp} \text{ is free}, \qquad u^{C}_t = 0 \text{ when } Q \text{ is free} $$

In PyPSA the heat pump's capacity is on the electricity side,
$Q^{hp}/COP^{min}$, with the share $COP^{min}/COP_t$ available at $t$; its yearly cost per kW of electricity is
$\Gamma^{hp}\,COP^{min}$.

$$ E^{B} = k_e\, B, \qquad P^{B} = k_p\, B, \qquad B \le B^{max} $$

except in the one-meter rules 5.6, where $P^{B}$ stays the number $k_p B^{ref}$.

$$ B^{max} = \begin{cases} T^{sub} & \text{subsidy cap on} \\ \max(\text{battery size list}) & \text{otherwise} \end{cases} $$

### Battery linear terms, taken at a reference size $B^{ref}$

$$ k_e = \frac{E^{B}(B^{ref})}{B^{ref}}, \qquad k_p = \frac{P^{B}(B^{ref})}{B^{ref}}, \qquad
\hat c^{B} = \frac{\mathrm{NetPrice}(B^{ref}) + \mathrm{Repl}(B^{ref})}{B^{ref}}, \qquad \hat a^{B} = \frac{a\,\psi\,\kappa\,B^{ref}}{B^{ref}} $$

First $B^{ref} = B^{max}$. If $B^* \ge 1$ kWh and the terms at $B^*$ differ from those at $B^{max}$ by more than 1 %
(or, where 5.6 applies, $|B^* - B^{max}| > 0.05\,B^{max}$), solved again once with $B^{ref} = B^*$.

### Checks and rounding

$$ \text{battery kept} \iff \mathrm{YC}\big(\text{with } B^*,\ \text{EMS included}\big) < \mathrm{YC}\big(\text{best system without battery}\big) $$

$$ Q = \lceil Q^* \rceil, \qquad Q^{hp} = \lceil Q^{hp*} \rceil, \qquad K = \mathrm{round}(K^*), \qquad B = \mathrm{round}(B^*) $$

where $\mathrm{YC}$ is the site's yearly cost (section 10.4); a free size below 1 is set to 0.

### Battery EMS check

The best system without the battery is optimised too; a battery sized here is kept only if its yearly cost with the
EMS costs is lower (above); a size fixed in the case is kept.

In each system without a technology (10.5) that keeps a battery the check is shorter. With $\mu \ge 0$ the shadow
price of $E^{B} \le k_e B^{max}$ in the solve: the site's yearly cost as a function of $E^{B}$ (the battery's own
price and reserve revenue aside) is convex in a linear programme, with slope $-((\hat c^{B} - \hat a^{B})/k_e + \mu)$
at the size found, so

$$ \mathrm{YC}(\text{without battery}) - \mathrm{YC}(\text{with } B^*,\ \text{EMS aside}) \;\ge\; \mu\, k_e B^* $$

and when $f^{S} = 0$, the solve is under the starting regime with no DUP held, and (no heat pump or no regime rule)
the year without battery is solved under the same regime:

$$ \mu\, k_e B^* \ge F^{EMS} + f^{A} A_B + C^{EMS}/\tau^{PV} \;\Rightarrow\; \text{battery kept, nothing more solved} $$

($\mu > 0$ only with the battery at $B^{max}$). Otherwise the year without battery is solved with the other sizes
kept at those found with it (operation only, $\ge$ the best system without battery). A battery that does not pay
against it does not pay against the best one either; it is left out and the system without it sized again. One kept
against it is kept (approximation: the other sizes are not sized again without the battery).

---

## 8. The battery check: the reference sweep

After the joint sizing, when it sizes the battery: for each size $B$ in a list $\mathcal{Z}$, the year of section 5 is
solved with that battery and the other blocks at their joint sizes; one size is kept by the rule below and set against
the joint size $B^{joint}$ (sizes, $V_B$, $I_B$, $\mathrm{PB}_B$, $\mathrm{LP}_B$ and $\mathrm{YC}$ of 10.4 for both).

### 8.1 Bill

$$
\mathrm{Bill}(I, E, r) = \sum_t \pi_{t,r} I_t\,\Delta t \;+\; \mathrm{CC}_r(I)
\;-\; \sum_t \varphi_t\,(1 - \mathbb{1}^{E}\sigma_t)\,E_t\,\Delta t
\;+\; \sum_t \mathbb{1}^{E}\,\sigma_t\,(PV_t - E_t)^+\,p^{E}\,\Delta t
$$

with $\mathrm{CC}_r(I)$ the capacity charges of the import profile $I$ (5.3 with the peaks equal to the highest
imports).

### 8.2 Battery, size $B$

$$ \Delta\mathrm{Bill}_B = \mathrm{Bill}_0 - \mathrm{Bill}_B, \qquad A_B = a\,\psi\,\kappa\,B $$

$$ \mathrm{EMS}_B = F^{EMS} + f^{A} A_B + f^{S} \max(\Delta\mathrm{Bill}_B,\, 0) $$

$$ V_B = \Delta\mathrm{Bill}_B + \Delta\mathrm{Heat}_B + A_B - \mathrm{EMS}_B $$

$\Delta\mathrm{Heat}_B$ = 0 without a heat pump; with one, the heat side's running cost (gas, levy, boiler O&M, CO2
bought) without battery minus with it: the battery changes when the heat pump runs.

$$ I_B = \mathrm{NetPrice}(B) + C^{EMS}, \qquad \mathrm{PB}_B = \frac{I_B}{V_B}, \qquad \mathrm{LP}_B = V_B\,\tau^{B} - I_B $$

$$ \mathrm{NetPrice}(B) = \begin{cases}
(1 - f^{sub})\, B\,p^{B}(B) & \text{percent, or threshold with } B \le T^{sub} \\
\max\big(B\,p^{B}(B) - f^{sub}\, T^{sub} p^{B}(T^{sub}),\, 0\big) & \text{threshold with } B > T^{sub} \\
\max\big(B\,p^{B}(B) - \text{amount},\, 0\big) & \text{fixed amount}
\end{cases}
\qquad T^{sub} = \mathrm{round}\Big(\frac{\sum_t L_t\,\Delta t}{365}\,\gamma\Big) $$

($\gamma$: OCAN factor, CH; without the OCAN rule $T^{sub}$ is a given size). Choice:

$$ B^* = \begin{cases}
\arg\max_{B:\ \mathrm{PB}_B \le \tau^{B}} \mathrm{LP}_B \quad (\text{else } \arg\min_B \mathrm{PB}_B) & \text{profit} \\
\arg\min_B \mathrm{PB}_B & \text{payback}
\end{cases} $$

The joint sizing minimises $\mathrm{YC}$ (10.4), with $(I_B + \mathrm{Repl}(B))/\tau^{PV}$ for the battery, over any
$B \le B^{max}$; the sweep maximises $\mathrm{LP}_B$ on $\mathcal{Z}$. The two can differ.

### 8.3 The boiler's size alone

A boiler that must meet the demand alone needs at least

$$ Q^{need} = \max_t \;\max\!\Big(H_t,\; \frac{\eta^{G}}{\varepsilon\,\phi}\,C_t\Big) \quad\text{(CO2 must be met, no external CO2; else } \max_t H_t\text{)} $$

and its year at a size $Q$ (the joint size) is reported with

$$ Y_Q = \sum_t (p^{g}_t + \lambda\varepsilon)\, g_t\,\Delta t + o^{Q} Q + \sum_t m^{G} \eta^{G} g_t\,\Delta t + \sum_t p^{CO2}_t\, q^{CO2}_t\,\Delta t, \qquad
\mathrm{LC}_Q = c^{Q} Q + Y_Q\,\tau^{Q} $$

$$ \text{covers}(Q) \iff \sum_t u^{H}_t \le 10^{-6} \sum_t H_t \;\;\text{and}\;\; \sum_t u^{C}_t \le 10^{-6} \sum_t C_t
\quad (\text{the CO2 condition only when the CO2 demand must be met}) $$

### 8.4 Sensitivity of the sizes

With the sizes $z^*$ of the joint sizing, for each installed sized block and the Voltiris modules $x$, the year of
section 5 (operation only, regime and DUP lock of the joint sizing) is solved at

$$ z = z^* \text{ except } z_x = (1 \pm 0.1)\, z^*_x $$

and reported with $\mathrm{YC}(z) - \mathrm{YC}(z^*)$ (10.4, the battery's EMS from the joint sizing's bill without
battery) and its grid import, self-sufficiency, gas, CO2 emitted, $\sum_t u^{H}_t \Delta t$ and
$\sum_t u^{C}_t \Delta t$ (unmet demand is not in $\mathrm{YC}$).

### 8.5 Technical summary

For each sized block of size $z$ with output $y_t$ (boiler and heat pump heat, storage heat given back, battery
discharge): full-load hours $\sum_t y_t \Delta t / z$ (cycles for storage), hours at full size
$\sum_t \Delta t\,[y_t \ge 0.99\,z]$ (storage: $h_t \ge 0.99\,K$; battery: $|x^{+}_t - x^{-}_t| \ge 0.99\,P^{B}$), and the
yearly cost of one more unit, $\Gamma$ of section 7.

---

## 9. Splitting the solved year (electricity)

With the battery's net power $\nu_t = \eta^{-}x^{-}_t - x^{+}_t$, $\nu^{+}_t = \max(\nu_t, 0)$,
$\nu^{-}_t = \max(-\nu_t, 0)$. With a heat pump, $L_t$ in this section and in 10.1 is the site's load $L_t + w_t$
(and $D_t$, $S_t$ are taken with it):

| Flow | Formula |
|---|---|
| PV to load | $\mathrm{pv2l}_t = \min(PV_t, L_t)$, of which Voltiris $\sigma_t\,\mathrm{pv2l}_t$ |
| PV to battery | $\mathrm{pv2b}_t = \min(\nu^{-}_t, S_t)$ |
| PV exported | $\mathrm{pvx}_t = PV_t - \mathrm{pv2l}_t - \mathrm{pv2b}_t$ |
| battery to load | $\mathrm{b2l}_t = \min(\nu^{+}_t, D_t)$ |
| battery to grid | $\mathrm{b2g}_t = \nu^{+}_t - \mathrm{b2l}_t$ |
| grid to load | $\mathrm{g2l}_t = L_t - \mathrm{pv2l}_t - \mathrm{b2l}_t$ |
| grid to battery | $\mathrm{g2b}_t = \nu^{-}_t - \mathrm{pv2b}_t$ |

Self-consumption and self-sufficiency:

$$ U = \sum_t \mathrm{pv2l}_t\,\Delta t + \min\!\Big(\textstyle\sum_t \mathrm{b2l}_t\,\Delta t \cdot \dfrac{\sum_t \mathrm{pv2b}_t}{\sum_t \nu^{-}_t},\;\; \eta^{+}\eta^{-}\sum_t \mathrm{pv2b}_t\,\Delta t\Big) $$

$$ \mathrm{SC} = \frac{U}{\sum_t PV_t\,\Delta t}, \qquad \mathrm{SS} = \frac{U}{\sum_t L_t\,\Delta t} $$

---

## 10. Results

### 10.1 Savings of the PV (against buying all the load, no battery)

$$
\mathrm{Sav}^{PV} = \sum_t \mathrm{pv2l}_t\,\pi_{t,r}\,\Delta t
+ \sum_t \varphi_t (1-\mathbb{1}^{E}\sigma_t)\,E_t\,\Delta t
+ \big(\mathrm{CC}_r(L) - \mathrm{CC}_r(I)\big)
- \sum_t \mathbb{1}^{E}\sigma_t (PV_t - E_t)^+ p^{E}\,\Delta t
= \Big(\sum_t \pi_{t,r} L_t\,\Delta t + \mathrm{CC}_r(L)\Big) - \mathrm{Bill}(I, E, r)
$$

(the first bracket is the bill without PV: all the load imported, no export, no EaaS fee).

### 10.2 Savings of the battery (against the system without it)

$$
\mathrm{Sav}^{B} = \sum_t \mathrm{b2l}_t\,\pi_{t,r}\,\Delta t
+ \sum_t \varphi_t (1-\mathbb{1}^{E}\sigma_t)\,\mathrm{b2g}_t\,\Delta t
- \sum_t \varphi_t (1-\mathbb{1}^{E}\sigma_t)\,\mathrm{pv2b}_t\,\Delta t
- \sum_t \mathrm{g2b}_t\,\pi_{t,r}\,\Delta t
+ \big(\mathrm{CC}(\text{without}) - \mathrm{CC}(\text{with})\big)
+ \text{other} = \mathrm{Bill}_0 - \mathrm{Bill}_B
$$

where "other" is the regime switch and the EaaS fee change (with a heat pump, also the change in its draw $w_t$).

### 10.3 Savings of the heat storage and of bought CO2

Heat storage, against the system without it ($g^{0}_t$: gas burnt without storage):

$$ \text{gas replaced} = \sum_t \frac{\eta^{out} s^{-}_t}{\eta^{G}}\,\Delta t, \qquad
\text{gas saved} = \sum_t \big(g^{0}_t - g_t\big)\Delta t, \qquad
\text{extra gas to fill it} = \text{gas replaced} - \text{gas saved} $$

valued at $p^{g}_t + \lambda\varepsilon$ at each step. Its yearly value, split by line:

$$ V_K = \Delta(\text{gas}) + \Delta(\text{levy}) + \Delta(\text{boiler O\&M}) + \Delta(\text{CO2 bought})
+ \big(o^{Q} + c^{Q}/\tau^{Q}\big)\big(Q^{0} - Q\big) - o^{K} K $$

($Q^{0}$: boiler size without storage.) It is split by every
line $j$ of the yearly cost (10.4, 10.5), the storage's own investment left out, so with a heat pump the bill and the
heat pump's terms are in it too:

$$ V_K = \sum_{j \,\ne\, c^{K}K/\tau^{K}} \big(\mathrm{YC}^{without}_{j} - \mathrm{YC}^{with}_{j}\big), \qquad \mathrm{PB}_K = \frac{c^{K} K}{V_K} $$

Bought CO2, against burning gas only for it:

$$ \mathrm{Sav}^{CO2} = \sum_t q^{CO2}_t\Big(\frac{p^{g}_t + \lambda\varepsilon + m^{G}\eta^{G}}{\varepsilon\,\phi} - p^{CO2}_t\Big)\Delta t $$

### 10.4 Site yearly cost

$$
\mathrm{YC} = \underbrace{\mathrm{Bill} + \sum_t (p^{g}_t + \lambda\varepsilon) g_t \Delta t + \sum_t m^{G}\eta^{G} g_t\Delta t + o^{Q}Q + o^{K}K
+ o^{hp}Q^{hp} + \sum_t p^{CO2}_t q^{CO2}_t \Delta t + F^{CO2} + \mathrm{EMS}_B - A_B}_{\text{running}}
\;+\; \underbrace{\frac{I^{PV}}{\tau^{PV}} + \frac{c^{Q} Q}{\tau^{Q}} + \frac{c^{hp} Q^{hp}}{\tau^{hp}} + \frac{c^{K} K}{\tau^{K}} + \frac{I_B + \mathrm{Repl}(B)}{\tau^{PV}}}_{\text{investment per year}}
$$

with $I^{PV}$ the Voltiris modules' price after subsidy (0 under EaaS) and the battery spread over the PV life (its
first purchase $I_B$ with the EMS hardware, and its replacements). The heat pump's electricity is in the Bill.

Heat pump figures: seasonal performance factor $\mathrm{SPF} = \sum_t COP_t w_t / \sum_t w_t$; its heat's cost per MWh
$= \big(\sum_t \pi_{t,r} w_t \Delta t + o^{hp}Q^{hp} + c^{hp}Q^{hp}/\tau^{hp}\big) / \big(\sum_t COP_t w_t \Delta t / 1000\big)$
(electricity at the import price; capacity charges and PV are in the Bill).

### 10.5 With and without each technology $X$

$\mathcal{X}$: the blocks the system could do without (not fixed, not followers, not the only source of a demand).
For $X \in \mathcal{X}$, the system without $X$ (and without what needs it) is sized again together (section 7).

$$ \Delta_X = \mathrm{YC}^{*}(\text{without } X) - \mathrm{YC}^{*}(\text{with } X) \qquad (\Delta_X > 0: X \text{ lowers the yearly cost}) $$

$$ \text{extra investment}_X = \sum I^{with} - \sum I^{without}, \qquad
\text{running saving}_X = \mathrm{running}^{without} - \mathrm{running}^{with}, \qquad
\text{payback}_X = \frac{\text{extra investment}_X}{\text{running saving}_X} $$

Effect on each line $j$ of the yearly cost: $\mathrm{YC}^{with}_{j} - \mathrm{YC}^{without}_{j}$ (below 0:
$X$ lowers that line).
