"""What the web page asks for. Generic: the blocks, the scenario presets and the input data are handled here; anything
model specific goes to the adapter that runs the chosen system (interface/adapters). Each public function takes and
returns plain JSON-ready data.

    options()            blocks, presets, run types (with their markets and columns), example case files and workbooks
    load_case(path)      a case file, with its workbook path made absolute
    inspect_workbook()   the workbook's columns, its time step (converted to 15 min when coarser), totals and profiles
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
from interface.tables import clean, read_table, rounded

APP_DIR = Path(__file__).resolve().parent              # interface/
ROOT = APP_DIR.parent
COMMON_DIR = ROOT / "common"
EXAMPLES_DIR = ROOT / "examples"
APP_DATA = APP_DIR / "app_data"         # uploads and converted workbooks
RUNS_DIR = APP_DIR / "app_runs"         # default result folders, one per tag
STEP_HOURS = timeseries.MODEL_STEP_MIN / 60


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# -- options and case files -----------------------------------------------------------------------------------------
def options() -> dict:
    cases, workbooks = [], []
    for folder, pattern in ((EXAMPLES_DIR, "**/"), (APP_DATA / "uploads", "")):
        if folder.is_dir():
            cases += [{"name": str(p.relative_to(folder)), "path": str(p)} for p in sorted(folder.glob(pattern + "case*.json"))]
            workbooks += [{"name": str(p.relative_to(folder)), "path": str(p)} for p in sorted(folder.glob(pattern + "*.xlsx"))
                          if not p.name.startswith(("results_", "~$"))]
    if RUNS_DIR.is_dir():
        cases += [{"name": f"{p.parent.name}/{p.name}", "path": str(p)} for p in sorted(RUNS_DIR.glob("*/case_*.json"))]
    return {"blocks": _json(COMMON_DIR / "blocks.json")["blocks"], "presets": _json(COMMON_DIR / "scenarios.json")["presets"],
            "run_types": {key: a.options() for key, a in adapters.ADAPTERS.items()},
            "cases": cases, "workbooks": workbooks, "runs_dir": str(RUNS_DIR), "model_step_min": timeseries.MODEL_STEP_MIN}


def load_case(path: str) -> dict:
    path = Path(path)
    case = json.loads(path.read_text(encoding="utf-8"))
    input_file = Path(case.get("input_file", ""))
    if not input_file.is_absolute():
        input_file = (path.parent / input_file).resolve()
    case["input_file"] = str(input_file)
    if case.get("market", {}).get("canton") and not case["market"].get("region"):
        case["market"]["region"] = case["market"].pop("canton")
    return {"case": case, "path": str(path)}


def save_upload(name: str, data: bytes) -> dict:
    folder = APP_DATA / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / Path(name).name
    target.write_bytes(data)
    return {"path": str(target), "name": target.name}


# -- workbook --------------------------------------------------------------------------------------------------------
_converted: dict = {}


def _to_model_step(path: str, table: pd.DataFrame, index: pd.DatetimeIndex, kinds: dict, time_names: dict) -> str:
    """The workbook at 15 minutes, written once to app_data/converted/ (rewritten when the file or the columns
    change). Only the time columns and the mapped columns are kept."""
    src = Path(path)
    key = (str(src.resolve()), src.stat().st_mtime, tuple(index[:2]), tuple(sorted(kinds.items())))
    if key not in _converted or not Path(_converted[key]).is_file():
        frame = timeseries.to_model_step(table[list(kinds)].reset_index(drop=True), index, kinds)
        dst = APP_DATA / "converted" / f"{src.stem}_{timeseries.MODEL_STEP_MIN}min.xlsx"
        dst.parent.mkdir(parents=True, exist_ok=True)
        timeseries.with_time_columns(frame, time_names).to_excel(dst, index=False)
        _converted[key] = str(dst)
    return _converted[key]


def inspect_workbook(path: str, year: int, columns: dict | None = None, run_type: str | None = None) -> dict:
    adapter = adapters.ADAPTERS[run_type or next(iter(adapters.ADAPTERS))]
    table = read_table(path)
    names = {**adapter.DEFAULT_COLUMNS, **(columns or {})}
    available = [str(c) for c in table.columns]
    roles = [dict(role=r, about=a, unit=u, kind=k, needed=n, block=b, column=names[r], found=names[r] in available)
             for r, a, u, k, n, b in adapter.COLUMN_ROLES]
    out = {"path": path, "columns": available, "roles": roles, "rows": len(table)}
    time_names = {k: names[k] for k in ("month", "day", "hour", "minute")}
    if not all(time_names[k] in available for k in ("month", "day", "hour")) or names["load_kw"] not in available:
        out["error"] = "The time columns or the load column are missing: map them below."
        return out
    t = table.dropna(subset=[time_names[k] for k in ("month", "day", "hour")]).reset_index(drop=True)
    try:
        index = timeseries.timestamps(t, year, time_names)
        step = timeseries.step_info(index)
    except (ValueError, KeyError) as exc:
        out["error"] = f"The time stamps cannot be built: {exc}"
        return out
    out["step"] = step
    if step["step_minutes"] != timeseries.MODEL_STEP_MIN:
        kinds = {r["column"]: r["kind"] for r in roles if r["found"] and r["kind"] != "time"}
        try:
            converted = _to_model_step(path, t, index, kinds, time_names)
        except ValueError as exc:
            out["error"] = str(exc)
            return out
        result = inspect_workbook(converted, year, columns, run_type)
        result["converted_from"] = {"path": path, **step, "kinds": kinds}
        return result
    frame = pd.DataFrame({"load": t[names["load_kw"]].values}, index=index)
    has = {key: names[key] in available for key in ("pv_w_per_module", "existing_pv_kw", "day_ahead_eur_kwh")}
    if has["pv_w_per_module"]:
        frame["pv_module_kw"] = t[names["pv_w_per_module"]].values / 1000
    if has["existing_pv_kw"]:
        frame["existing_pv"] = t[names["existing_pv_kw"]].fillna(0).values
    if has["day_ahead_eur_kwh"]:
        frame["day_ahead"] = t[names["day_ahead_eur_kwh"]].values
    kwh = frame.drop(columns=[c for c in ("day_ahead",) if c in frame]) * STEP_HOURS
    monthly = kwh.groupby(kwh.index.month).sum().reindex(range(1, 13), fill_value=0)
    hourly = frame.resample("h").mean()
    totals = {
        "start": frame.index[0].isoformat(), "end": frame.index[-1].isoformat(), "steps": len(frame),
        "step_minutes": int(round(STEP_HOURS * 60)),
        "load_mwh": kwh["load"].sum() / 1000, "load_peak_kw": frame["load"].max(),
        "load_mean_kw": frame["load"].mean(),
    }
    if has["pv_w_per_module"]:
        totals["pv_kwh_per_module"] = kwh["pv_module_kw"].sum()
        totals["pv_peak_w_per_module"] = frame["pv_module_kw"].max() * 1000
    if has["existing_pv_kw"]:
        totals["existing_pv_mwh"] = kwh["existing_pv"].sum() / 1000
        totals["existing_pv_peak_kw"] = frame["existing_pv"].max()
    if has["day_ahead_eur_kwh"]:
        da = frame["day_ahead"]
        totals.update(day_ahead_mean=da.mean(), day_ahead_min=da.min(), day_ahead_max=da.max(),
                      day_ahead_negative_h=float((da < 0).sum() * STEP_HOURS), day_ahead_missing=int(da.isna().sum()))
    out.update(has=has, totals=clean(totals),
               monthly={c: rounded(monthly[c], 3) for c in monthly.columns},
               hourly={"start": hourly.index[0].isoformat(), **{c: rounded(hourly[c], 4) for c in hourly.columns}})
    return out


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
        _log(f"Reading the case file {case_path.name}, the parameters and the workbook ...")
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
