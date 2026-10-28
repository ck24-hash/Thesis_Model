# greenhouse: the site's demand

Today: the electricity load, kW per step, from the workbook column `Loadcurve (kW)` (role `load_kw`). It is a fixed
load on the bus `main` (PyPSA `Load` named `load`). No parameter files.

Its yearly energy is used by the battery block for a subsidy threshold that depends on the load (CH's OCAN rule).

Not built yet (PLAN.md section 6, step 2): heat demand, CO2 demand.
