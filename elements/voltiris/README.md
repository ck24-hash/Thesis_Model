# voltiris: the Voltiris modules

**Output.** kW per step = yield of one module (workbook column `Production voltiron (W)`, role `pv_w_per_module`)
/ 1000 x module count. It must run (no curtailment): a PyPSA generator `pv` with its output fixed to that profile.

**Money.** Price = modules x module Wp x price per Wp; PV subsidy (percent, fixed, or up to a module count); life.

**Business model.** `direct_sales`: the grower buys the modules and gets the feed-in on every export. `eaas`: Voltiris
owns them, the grower pays a price per MWh of Voltiris energy used on site (split pro rata with existing PV each
step), and gets the feed-in on the existing PV's exports only (`business_model.py`). Under EaaS the system sets the
grid's export value and bounds (decided 28 Oct 2026, PLAN.md section 7).

Parameters (`params/`, from the reference model's files; money in CHF, converted with `common/fx.json`):

| Group | Values |
|---|---|
| `tech/default.json` | `module_wp` 146 (the yield file says 145; to confirm, as in the reference) |
| `capex/default.json` | `pv_per_wp` 1.80 CHF |
| `finance/default.json` | `pv_life_yr` 25; also the horizon of the battery study, with or without Voltiris |
| `subsidies/<country>/...` | `pv`: CH GE 0%, NL 0%, FR 50% (FR to confirm, as in the reference) |
| `business_models/` | `direct_sales`, `eaas` (180 CHF/MWh) |
