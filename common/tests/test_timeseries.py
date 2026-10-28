"""Checks of common/timeseries.py on invented numbers: python -m pytest common/tests -q"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # the project root

from common import timeseries as ts  # noqa: E402


def frame(step_min: int, hours: int = 24) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    index = pd.date_range("2026-01-01", periods=hours * 60 // step_min, freq=f"{step_min}min")
    rng = np.random.default_rng(1)
    values = pd.DataFrame({"load_kw": rng.uniform(50, 150, len(index)), "heat_kwh": rng.uniform(0, 80, len(index)),
                           "price": rng.uniform(-0.05, 0.3, len(index))})
    return values, index


def test_step_found():
    for step in (15, 30, 60):
        _, index = frame(step)
        assert ts.step_info(index) == {"step_minutes": step, "irregular_steps": 0, "rows": len(index)}


def test_hourly_to_15_min():
    values, index = frame(60)
    out = ts.to_model_step(values, index, {"load_kw": "power", "heat_kwh": "energy", "price": "price"})
    assert len(out) == 96 and ts.step_info(out.index)["step_minutes"] == 15
    assert out.index[0] == index[0] and out.index[-1] == index[-1] + pd.Timedelta(minutes=45)
    # power and price repeated, energy split over the four quarter hours
    assert np.allclose(out["load_kw"].to_numpy().reshape(-1, 4), values["load_kw"].to_numpy()[:, None])
    assert np.allclose(out["price"].to_numpy().reshape(-1, 4), values["price"].to_numpy()[:, None])
    assert np.isclose(out["heat_kwh"].sum(), values["heat_kwh"].sum())
    # the energy of a power curve is the same before and after
    assert np.isclose(out["load_kw"].sum() * 0.25, values["load_kw"].sum() * 1.0)


def test_half_hour_to_15_min():
    values, index = frame(30)
    out = ts.to_model_step(values, index, {"load_kw": "power", "heat_kwh": "energy", "price": "price"})
    assert len(out) == 2 * len(values)
    assert np.isclose(out["heat_kwh"].sum(), values["heat_kwh"].sum())


def test_15_min_unchanged():
    values, index = frame(15)
    out = ts.to_model_step(values, index, {"load_kw": "power", "heat_kwh": "energy", "price": "price"})
    assert (out.index == index).all() and np.allclose(out.to_numpy(), values.to_numpy())


def test_full_year():
    index = pd.date_range("2026-01-01", periods=8760, freq="h")
    out = ts.to_model_step(pd.DataFrame({"p": np.ones(8760)}, ), index, {"p": "power"})
    assert len(out) == 35040 and out.index[-1] == pd.Timestamp("2026-12-31 23:45")


def test_refused():
    values, index = frame(60)
    with pytest.raises(ValueError, match="No kind"):
        ts.to_model_step(values, index, {"load_kw": "power", "price": "price"})
    with pytest.raises(ValueError, match="Unknown kind"):
        ts.to_model_step(values, index, {"load_kw": "power", "heat_kwh": "kWh", "price": "price"})
    for step in (5, 20):
        v, i = frame(step)
        with pytest.raises(ValueError, match="cannot be brought"):
            ts.to_model_step(v, i, {"load_kw": "power", "heat_kwh": "energy", "price": "price"})


def test_time_columns_round_trip():
    values, index = frame(60)
    table = ts.with_time_columns(values.set_index(index))
    del table["Minute"]   # hourly files often have no minute column
    assert (ts.timestamps(table, 2026) == index).all()


def test_convert_file(tmp_path):
    values, index = frame(60, hours=48)
    src = tmp_path / "hourly.xlsx"
    ts.with_time_columns(values.set_index(index)).to_excel(src, index=False)
    r = ts.convert_file(src, tmp_path / "out.xlsx", 2026, {"load_kw": "power", "heat_kwh": "energy"})
    back = pd.read_excel(tmp_path / "out.xlsx")
    assert r["step_minutes"] == 60 and r["rows_out"] == 192
    assert list(back.columns) == ["Month", "Day", "Hour", "Minute", "load_kw", "heat_kwh"]
    assert np.isclose(back["heat_kwh"].sum(), values["heat_kwh"].sum())
