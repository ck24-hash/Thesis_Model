# existing_pv: PV already on site

Its measured output, kW per step, from the column `Current PV feed-in (kW)` of the block's own input file (role
`existing_pv_kw`; missing values count as 0). An hourly file is fine: it is brought to 15 min when the system runs
(example: `examples/blocks/existing_pv_2026_hourly.xlsx`). No parameter files: it is not sized and its cost is sunk.

It must run, like Voltiris. The system adds both to the network as one generator `pv` with the summed output, behind
the site's one meter, as in the reference model; so a case with existing PV gives the reference model's results to the
last digit. Under EaaS, the grower keeps the feed-in on the existing PV's share of the exports.
