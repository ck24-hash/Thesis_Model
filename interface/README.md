# interface: one page for every run

```
python interface/app.py
```

It opens http://127.0.0.1:8775 (`--port` to change it, `--no-browser` to only print the address). Keep the console
window open while you use it; Ctrl+C stops it. It needs the models' Python packages
(`elements/battery_reference/requirements.txt`).

## Pages

1. **System**: a drawing of the greenhouse with every block around it; click a block to add or remove it (flows light
   up by carrier; dashed = not built yet). Or load a case file or a scenario preset (`common/scenarios.json`, the
   thesis matrix), and set the data year. The Sizing row says that every ticked sized block is sized together. The
   links between blocks apply when you click:
   greenhouse and grid always stay, the gas supply comes and goes with the gas boiler, a heat storage brings the gas
   boiler if there is no heat source, and taking out the last heat source takes the heat storage with it. The blocks
   chosen pick the model that runs them (the run type); when two fit, choose one. A system no model can run yet is
   shown with the reason, and cannot be run.
   - **One page per chosen block**, under System, with its technical side only:
     - Greenhouse demand, Voltiris, Existing PV, Grid, Gas supply, Heat pump, Heat storage, External CO2: the block's
       own input file (pick, upload or type a path; its time step, columns, and its curves by year, month or week). A
       coarser step (hourly, 30 min, daily) is shown as converted; the system converts it when it runs
       (`common/timeseries.py`).
     - Greenhouse demand: the CO2 demand mode (must be met, or by-product of heating), with a CO2 source. Voltiris:
       modules and module power. Grid: connection limits, regime. Battery: technology with what 100 kWh gives the
       optimiser (live), the grid services reserve, a Size card (sized by the model or fixed size, the subsidy cap)
       and a "Check against the reference sweep" card (the sweep's objective lifetime profit or payback, its sizes,
       the fine grid; switched on or off on the Run page). Gas supply: fixed price, emission factor, carbon levy. Gas boiler: efficiency,
       usable flue gas CO2, what the demand asks of it, a Size card (sized by the model or fixed size, 0 allowed).
       Heat pump: COP (dynamic or constant), supply and reference temperatures, its size (sized by the model, or
       fixed), and the setup check's numbers (COP range, electricity to give the demand, its heat price against the
       boiler's). Heat storage: technology, heat loss model, a Size card (sized by the model or fixed size, 0
       allowed). External CO2: fixed price, fixed cost, most CO2 per hour, and what buying costs against burning gas.
     - A block not built yet: what it will do; the system cannot run.
2. **Input data**: every chosen block's file and status, and all curves on one chart, by year (daily means), month or
   week (hourly means), each curve switchable.
3. **General**, the items not tied to one block (`general/`): Market (country, region, utility; the run's currency and
   tariff), Commercial (business model, prices, lifetimes, ancillary rate, boiler, heat pump and heat storage prices,
   O&M and lives), Subsidies (an On/Off switch per technology, Voltiris modules and battery: off writes a share and
   amount of 0 into the case file's overrides), EMS. Shown when they apply, and a field about one block only when the
   system has it.
4. **Run**: the setup check (nothing is solved), what runs after the sizing (ticks: the sensitivity, each size -10 %
   and +10 % with the operation only; the battery check against the reference sweep, when the model sizes the
   battery), the run with its progress and log, other overrides (JSON), the case file, every parameter used. It writes `case_<tag>.json` (system format) to the output folder and runs it.
5. **Results**, in tabs: System, always, in three parts: "Technical: what was chosen and what it does" (each piece
   of equipment at its size: how the size was found, what one more unit costs per year, energy given and share of
   the demand, full-load hours or cycles, hours at full size; the year's energy; what each technology changes
   technically), "Financial: what it costs and what each technology is worth" (each technology with and without it:
   yearly cost, extra investment, running cost, payback, each linked to its details; the site's yearly cost, running
   and investments per year), "How much the sizes matter" (the sensitivity table, rows with unmet demand shaded; the
   battery check card);
   Electricity, always (supply and demand per month and for one week, what the PV saves flow by flow,
   self-consumption and self-sufficiency, money to and from the grid with the bill without PV, month by month; without
   and with the battery when there is one); for the battery Battery (key numbers, why this size, where the value comes
   from, what it saves flow by flow), Bills and payback, Over the year, Month by month; Gas boiler and
   Heat storage, one tab each (key numbers, why this size, per day, month by month; for the heat
   storage also where its value comes from, the gas its heat replaces and one week hourly); Heat pump (size, heat given, electricity drawn, SPF,
   cost per MWh of heat, heat by source per month, electricity and COP per month, COP against the outside
   temperature, one week hourly); CO2, with external CO2 (flue gas against bought CO2 per month and per day, with the
   prices; with a boiler, what buying saves against burning gas); Files. Each technology's "With and without"
   (verdict, advantages and disadvantages, the yearly cost from without to with it with the value on each bar: the
   two totals and each line's change, line by line, sizes and key
   figures, or why it is not evaluated) comes after the key numbers of its tab: Voltiris and Existing PV on
   Electricity, the others on their own tab. A tab shows only when the run has that study. After a refresh the last
   run's results come back, and a run still going is followed again (its steps and log). One run at a time: Run
   during a run shows that run's progress.

The five sections are tabs along the top. A section with pages of its own (System with its blocks, General with its
items) lists them in the side menu; the menu button (top left) hides or shows it. Parameter fields always show the
value in use, which can be changed at any time: the typed value, else the one set in the other overrides (JSON) or
by the ancillary switch (the field is shaded, its tip says which), else the parameter file's. "Defaults" in a card or
group title puts that card or group back to the parameter files' values. A default converted from another currency is shown rounded and used exact unless it is
changed. An i next to a field explains it.

The address keeps the page (`#voltiris`, `#run`), so a refresh opens the same page.

## Run types

A run type is one module in `adapters/`, the only place that knows a model. It gives `BLOCKS_REQUIRED` and
`BLOCKS_ALLOWED`, its markets, its columns (with unit and kind), its parameters, a preview, a run, and its progress
stages. When several fit the chosen blocks, the System page shows a choice and the case file keeps it in
`system.run_type`; the first that fits is the default. Today there are two:

- `blocks` (`system_study.py`, the default): the blocks in `elements/` and the engine in `system/`, as
  `python system/run_case.py case_<tag>.json` runs them. It needs greenhouse and grid. Its progress stages: read the
  inputs, sizing (every ticked block sized together), the year at the chosen sizes, with and without each
  technology, the money, sensitivity, battery check, write the files.
- `battery_study` (`battery_study.py`): the reference model `elements/battery_reference`. It reads one workbook, so the
  run writes the blocks' inputs as `input_<tag>.xlsx` in its format and the case as `case_<tag>_reference.json`, and
  runs that exactly as `python elements/battery_reference/run_case.py case_<tag>_reference.json` would.

For a battery system both write the same tables, drawn by the same results panel (`battery_view.py`, which shapes
every tab's results: electricity side, battery, gas boiler, heat storage, heat pump, CO2, the site's yearly cost,
with and without). The reference run type shows the System, Electricity and battery tabs, without the with and
without. A reference case file (one workbook, no `blocks`) opens with every block reading that workbook.

The battery model has no ancillary switch of its own: "off" in the battery card writes
`{"ancillary": {"rate_per_kw_year": 0, "reserve": {"mode": "percent", "frac": 0}}}` into the case file's overrides.

## Files

```
app.py              starts the server and opens the browser
server.py           local web server (standard library), 127.0.0.1 only
api.py              generic: options, case files, each block's input file and its time step, run state
tables.py           JSON-ready values, the workbook kept in memory
adapters/           one module per run type
web/                the page: index.html, app.js, style.css, chart.umd.js (Chart.js 4.4.1, MIT licence)
app_data/           uploads (created when used)
app_runs/<tag>/     default output folders (created when used)
```
