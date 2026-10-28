"""What the web page asks for. Generic: the blocks, the scenario presets, each block's input file and the run state
are handled here; the model that runs the chosen system is the run type's adapter (interface/adapters). Each public
function takes and returns plain JSON-ready data. Cases are in the system format (system/setup.py): one input file
per block.

    options()            blocks and their columns, presets, run types (markets, parameters), example files
    load_case(path)      a case file (either format) in the system format, its input files made absolute
    inspect_block()      one block's input file: its columns, its time step, totals and profiles
    parameters()         the market's parameters for the run type
    preview()            what the run will do, without solving
    start_run()          the run in the background; run_status() and run_results() follow
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from pathlib import Path

import pandas as pd

from common import timeseries
from interface import adapters
from interface.adapters.battery_view import TIME_ROLES
from interface.tables import clean, read_table, rounded
from system import setup

APP_DIR = Path(__file__).resolve().parent              # interface/
ROOT = APP_DIR.parent
COMMON_DIR = ROOT / "common"
EXAMPLES_DIR = ROOT / "examples"
APP_DATA = APP_DIR / "app_data"         # uploads
RUNS_DIR = APP_DIR / "app_runs"         # default result folders, one per tag
STEP_HOURS = timeseries.MODEL_STEP_MIN / 60
TO_KW = {"kW": 1.0, "W per module": 0.001, "W": 0.001}   # power columns shown as kW (or kW per module)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# -- options and case files -----------------------------------------------------------------------------------------
def options() -> dict:
    cases, workbooks = [], []
    for folder, pattern in ((EXAMPLES_DIR, "**/"), (APP_DATA / "uploads", "")):
        if folder.is_dir():
            cases += [{"name": p.relative_to(folder).as_posix(), "path": str(p)}
                      for p in sorted(folder.glob(pattern + "case*.json"))]
            workbooks += [{"name": p.relative_to(folder).as_posix(), "path": str(p)}
                          for p in sorted(folder.glob(pattern + "*.xlsx"))
                          if not p.name.startswith(("results_", "input_", "~$"))]
    if RUNS_DIR.is_dir():
        cases += [{"name": f"{p.parent.name}/{p.name}", "path": str(p)} for p in sorted(RUNS_DIR.glob("*/case_*.json"))
                  if not p.stem.endswith("_reference")]
    columns = {key: {"time": [dict(role=r, about=a, unit=u, kind=k, needed=n) for r, a, u, k, n, _ in TIME_ROLES],
                     "data": m.COLUMNS, "defaults": setup.column_names(key)}
               for key, m in setup.BLOCKS.items() if m.COLUMNS}
    return {"blocks": _json(COMMON_DIR / "blocks.json")["blocks"], "presets": _json(COMMON_DIR / "scenarios.json")["presets"],
            "run_types": {key: a.options() for key, a in adapters.ADAPTERS.items()}, "block_columns": columns,
            "cases": cases, "workbooks": workbooks, "runs_dir": str(RUNS_DIR), "model_step_min": timeseries.MODEL_STEP_MIN}


def load_case(path: str) -> dict:
    return {"case": setup.load_case(Path(path)), "path": str(path)}


def save_upload(name: str, data: bytes) -> dict:
    folder = APP_DATA / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / Path(name).name
    target.write_bytes(data)
    return {"path": str(target), "name": target.name}


# -- one block's input file -----------------------------------------------------------------------------------------
def inspect_block(block: str, path: str, year: int, columns: dict | None = None) -> dict:
    """The file's columns and what the block reads from them, the time step found (a coarser one is converted to
    15 min when the system runs; shown converted here), and per column: totals, monthly values, hourly profile."""
    m = setup.BLOCKS[block]
    table = read_table(path)
    names = setup.column_names(block, columns)
    available = [str(c) for c in table.columns]
    roles = ([dict(role=r, about=a, unit=u, kind=k, needed=n, column=names[r], found=names[r] in available)
              for r, a, u, k, n, _ in TIME_ROLES]
             + [dict(c, column=names[c["role"]], found=names[c["role"]] in available) for c in m.COLUMNS])
    out = {"block": block, "path": path, "columns": available, "roles": roles, "rows": len(table)}
    if not all(names[k] in available for k in ("month", "day", "hour")):
        out["error"] = "The time columns are missing: map them below."
        return out
    data = [c for c in m.COLUMNS if names[c["role"]] in available]
    if not data:
        out["error"] = "No column of this block was found: map it below."
        return out
    try:
        frame, step = setup.read_table(table, year, names, {names[c["role"]]: c["kind"] for c in m.COLUMNS})
    except (ValueError, KeyError) as exc:
        out["error"] = f"The time stamps cannot be built: {exc}"
        return out
    series = []
    for c in data:
        s = frame[names[c["role"]]].astype(float)
        entry = {k: c[k] for k in ("role", "about", "unit", "kind")} | {"column": names[c["role"]]}
        if c["kind"] == "price":
            monthly = s.groupby(s.index.month).mean()
            entry.update(mean=s.mean(), min=s.min(), max=s.max(), missing=int(s.isna().sum()),
                         negative_h=float((s < 0).sum() * STEP_HOURS))
        else:
            kwh = s * TO_KW.get(c["unit"], 1.0) * STEP_HOURS
            monthly = kwh.groupby(kwh.index.month).sum()
            entry.update(total_kwh=kwh.sum(), peak=s.max(), mean=s.mean(), missing=int(s.isna().sum()))
        entry["monthly"] = rounded(monthly.reindex(range(1, 13), fill_value=0), 3)
        entry["hourly"] = rounded(s.resample("h").mean(), 4)
        series.append(entry)
    out.update(step=step, converted=step["step_minutes"] != timeseries.MODEL_STEP_MIN,
               start=frame.index[0].isoformat(), end=frame.index[-1].isoformat(), steps=len(frame),
               hourly_start=frame.index[0].floor("h").isoformat(), series=series)
    return clean(out)


# -- parameters and preview: the adapter's -------------------------------------------------------------------------
def parameters_for_page(run_type: str, market: dict, business_model: str = "direct_sales",
                        overrides: dict | None = None) -> dict:
    return adapters.ADAPTERS[run_type].parameters_for_page(market, business_model, overrides)


def preview(case: dict) -> dict:
    return adapters.for_case(case).preview(case)


# -- running ---------------------------------------------------------------------------------------------------------
class Run:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = "idle"
        self.run_type = None
        self.log: list[str] = []
        self.stage = 0
        self.started = self.finished = None
        self.error = None
        self.results = None
        self.files: dict = {}
        self.done = 0
        self.total = 0


RUN = Run()


def _log(*args, end="\n", **_):
    text = " ".join(str(a) for a in args) + end
    with RUN.lock:
        RUN.log.append(text)
        adapter = adapters.ADAPTERS.get(RUN.run_type)
        if adapter is not None:
            adapter.track(RUN, text)


def _tag(case: dict) -> str:
    tag = str(case.get("tag") or "study").strip()
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in tag) or "study"


def start_run(case: dict, output_dir: str | None = None) -> dict:
    adapter = adapters.for_case(case)
    with RUN.lock:
        if RUN.state == "running":
            return {"error": "A run is already going."}
        RUN.__init__()
        RUN.state, RUN.started, RUN.run_type = "running", time.time(), adapter.ID
    tag = _tag(case)
    out_dir = Path(output_dir) if output_dir else RUNS_DIR / tag
    threading.Thread(target=_run, args=(adapter, dict(case, tag=tag), out_dir), daemon=True).start()
    return {"started": True, "output_dir": str(out_dir), "tag": tag, "run_type": adapter.ID}


def _run(adapter, case: dict, out_dir: Path):
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        tag = case["tag"]
        case_path = out_dir / f"case_{tag}.json"
        to_save = {k: v for k, v in case.items() if v not in (None, {}, [])}
        to_save["output_dir"] = str(out_dir)
        case_path.write_text(json.dumps(to_save, indent=2), encoding="utf-8")
        _log(f"Reading the case file {case_path.name}, the parameters and the input files ...")
        page, files = adapter.run(case_path, out_dir, tag, _log)
        with RUN.lock:
            RUN.results = page
            RUN.files = {**files, "case": str(case_path), "folder": str(out_dir)}
            RUN.state, RUN.stage = "done", max(s for s, _, _ in adapter.STAGE_LABELS)
    except Exception as exc:
        with RUN.lock:
            RUN.state = "error"
            RUN.error = f"{type(exc).__name__}: {exc}"
            RUN.log.append("\n" + traceback.format_exc())
    finally:
        RUN.finished = time.time()


def run_status(since: int = 0) -> dict:
    with RUN.lock:
        elapsed = ((RUN.finished or time.time()) - RUN.started) if RUN.started else 0
        return {"state": RUN.state, "run_type": RUN.run_type, "stage": RUN.stage, "log": RUN.log[since:],
                "log_length": len(RUN.log), "elapsed": elapsed, "error": RUN.error, "files": RUN.files,
                "done": RUN.done, "total": RUN.total}


def run_results() -> dict:
    with RUN.lock:
        if RUN.results is None:
            return {"error": "No finished run yet."}
        return {**RUN.results, "files": RUN.files}


def result_file(kind: str) -> Path | None:
    with RUN.lock:
        path = RUN.files.get(kind)
    return Path(path) if path and kind in ("summary", "results", "case") else None
