# greenhouse: the site's demand

One input file, three curves (a block with several curves keeps them in the same file):

| Role | Default column | Unit | Needed |
|---|---|---|---|
| `load_kw` | `Loadcurve (kW)` | kW per step | always |
| `heat_kw` | `Heat demand (kW)` | kW per step | with a heat source (gas boiler, heat pump) |
| `co2_kg_h` | `CO2 demand (kg/h)` | kg/h per step | with a CO2 source (gas boiler, external CO2) |

The load file's time steps are the run's: every other block's file must cover them.

**Electricity**: a fixed load on the bus `main` (PyPSA `Load` named `load`). Its yearly energy also sets the
battery's subsidy threshold in CH (OCAN rule). A heat pump's electricity comes on top of it (`system/dispatch.py`).

**Heat and CO2**: with a heat source, the `Load` `heat_demand` on the bus `heat`; with a CO2 source, when the CO2
demand must be met, the `Load` `co2_demand` on the bus `co2`. Each has a slack (`heat_unmet`, `co2_unmet`) that
covers what the system cannot give, at a penalty high enough that it is used only when nothing else can (A15). In
the joint sizing there is no heat slack when a heat source's size is free, and no CO2 slack when the boiler's is: the
demand must be met. The engine adds free sinks for the heat and CO2 the greenhouse does not take (`heat_release`,
`co2_vent`).

**Setting** (case file, `blocks.greenhouse.co2_mode`, A4):

- `required` (default): the CO2 demand must be met. The boiler also runs when only CO2 is needed, and its extra heat
  is released.
- `by_product`: the CO2 demand is not in the optimisation, the boiler runs for heat only. The greenhouse takes its
  CO2 while it runs, up to the demand; the rest of the demand is reported as unmet.

With external CO2 the mode is always `required` (bought CO2 can always meet the demand, A21).

**Parameters** (`params/demand/default.json`): `unmet_heat_penalty_per_kwh` 10 and `unmet_co2_penalty_per_kg` 10.
They are solver devices, not prices: they only need to be well above any real cost of heat or CO2.
