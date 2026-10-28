# existing_pv: PV already on site

Its measured output, kW per step, from the workbook column `Current PV feed-in (kW)` (role `existing_pv_kw`; missing
values count as 0). It must run: a PyPSA generator `existing_pv` with its output fixed to that profile. No parameter
files: it is not sized and its cost is sunk.

It serves the same load as Voltiris. Under EaaS, the grower keeps the feed-in on its share of the exports.

Difference with the reference model: there, Voltiris and existing PV are one generator `pv`; here they are two. The
LP is the same problem, but the PV is added in a different order, so a case with existing PV matches the reference
only to the last digits: on the CH test case, same size and regime, largest difference 7e-10 (`system/README.md`).
