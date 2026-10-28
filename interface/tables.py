"""Helpers shared by the API and the adapters: JSON-ready values and the workbook kept in memory."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd


def clean(obj):
    """JSON-ready: numpy to Python, NaN and infinity to None, DataFrames to {columns, index, rows}."""
    if isinstance(obj, pd.DataFrame):
        return {"columns": [str(c) for c in obj.columns], "index": [clean(i) for i in obj.index],
                "rows": [[clean(v) for v in row] for row in obj.itertuples(index=False)]}
    if isinstance(obj, pd.Series):
        return [clean(v) for v in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        value = float(obj)
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    return obj


def rounded(series: pd.Series, digits: int = 3) -> list:
    return [None if pd.isna(v) else round(float(v), digits) for v in series.tolist()]


_tables: dict = {}
KEEP = 12   # workbooks kept in memory (one per block, a few cases)


def read_table(path: str) -> pd.DataFrame:
    """A workbook's first sheet, kept in memory until the file changes."""
    p = Path(path)
    name, mtime = str(p.resolve()), p.stat().st_mtime
    if _tables.get(name, (None,))[0] != mtime:
        _tables.pop(name, None)
        while len(_tables) >= KEEP:
            _tables.pop(next(iter(_tables)))
        _tables[name] = (mtime, pd.read_excel(p))
    return _tables[name][1].copy()
