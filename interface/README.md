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
   thesis matrix), and set the data year. The blocks chosen pick the model that runs them (the run type); when two
   fit, choose one. A system no model can run yet is shown with the reason, and cannot be run.
   - **One page per chosen block**, under System, with its technical side only:
     - Greenhouse demand, Voltiris, Existing PV, Grid: the block's own input file (pick, upload or type a path; its time
       step, columns, and its curves by year, month or week). A coarser step (hourly, 30 min) is shown as converted;
       the system converts it when it runs (`common/timeseries.py`).
     - Voltiris: modules and module power. Grid: connection limits, regime. Battery: technology with what 100 kWh
       gives the optimiser (live), the grid services reserve, the sizing.
     - A block not built yet: what it will do; the system cannot run.
2. **Input data**: every chosen block's file and status, and all curves on one chart, by year (daily means), month or
   week (hourly means), each curve switchable.
3. **General**, the items not tied to one block (`general/`): Market (country, region, utility; the run's currency and
   tariff), Commercial (business model, prices, lifetimes, ancillary rate), Subsidies, EMS. Shown when they apply.
4. **Run**: the setup check (nothing is solved), the run with its progress and log, other overrides (JSON), the case
   file, every parameter used. It writes `case_<tag>.json` (system format) to the output folder and runs it.
5. **Results**: the run type's results and the files.

The address keeps the page (`#voltiris`, `#run`), so a refresh opens the same page.

## Run types

A run type is one module in `adapters/`, the only place that knows a model. It gives `BLOCKS_REQUIRED` and
`BLOCKS_ALLOWED`, its markets, its columns (with unit and kind), its parameters, a preview, a run, and its progress
stages. When several fit the chosen blocks, step 1 shows a choice and the case file keeps it in `system.run_type`;
the first that fits is the default. Today there are two, for the same blocks (greenhouse electricity load + grid +
battery, with or without Voltiris and existing PV) and the same case file:

- `blocks` (`system_study.py`, the default): the blocks in `elements/` and the engine in `system/`, as
  `python system/run_case.py case_<tag>.json` runs them.
- `battery_study` (`battery_study.py`): the reference model `elements/battery_reference`. It reads one workbook, so the
  run writes the blocks' inputs as `input_<tag>.xlsx` in its format and the case as `case_<tag>_reference.json`, and
  runs that exactly as `python elements/battery_reference/run_case.py case_<tag>_reference.json` would.

Both write the same tables, drawn by the same results panel (`battery_view.py`). A reference case file (one
workbook, no `blocks`) opens with every block reading that workbook.

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
