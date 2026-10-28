# voltiris: the Voltiris modules

**Output.** kW per step = yield of one module (column `Production voltiron (W)` of the block's own input file, role
`pv_w_per_module`) / 1000 x module count. It must run (no curtailment). The system adds it to the network together
with the existing PV, as one generator `pv` with the summed output behind the site's meter, as in the reference model.

**Settings.** `modules` in the case's `blocks.voltiris`.

**Parameters** (`params/tech/default.json`, from the reference model): `module_wp` 146 Wp (the yield file says 145;
to confirm, as in the reference).

The modules' price, life, subsidy and business model (direct sales or EaaS) are general items: `general/commercial`
and `general/subsidies`.
