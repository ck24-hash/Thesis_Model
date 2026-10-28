"""The study's time series, read from the input workbook: load, Voltiris yield per module, existing PV, day-ahead."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# The input workbook's column names (the "+PV" input files); a case file may rename them under "columns".
DEFAULT_COLUMNS = {
    "load_kw": "Loadcurve (kW)",
    "day_ahead_eur_kwh": "Day ahead kWh",
    "pv_w_per_module": "Production voltiron (W)",
    "existing_pv_kw": "Current PV feed-in (kW)",
    "month": "Month",
    "day": "Day",
    "hour": "Hour",
    "minute": "Minute",
}


@dataclass
class Study:
    """Every series is in kW per step (load, PV) on one DatetimeIndex; dt is the step in hours."""
    index: pd.DatetimeIndex
    dt: float
    modules: int
    load: pd.Series
    volt_pv: pd.Series           # Voltiris PV, all modules
    existing_pv: pd.Series | None
    pv_total: pd.Series          # Voltiris + existing PV: both compete for the same load
    da_price: pd.Series | None   # day-ahead price, local currency per kWh; None when the input has no such column

    @property
    def yearly_load_kwh(self) -> float:
        return (self.load * self.dt).sum()


def from_frame(df: pd.DataFrame, *, year: int, modules: int, use_existing_pv: bool, eur_to_local: float,
               dt: float = 0.25, columns: dict | None = None) -> Study:
    c = {**DEFAULT_COLUMNS, **(columns or {})}
    df = df.dropna(subset=[c["month"], c["day"], c["hour"], c["minute"]]).reset_index(drop=True)
    df["timestamp"] = pd.to_datetime(dict(year=year, month=df[c["month"]], day=df[c["day"]],
                                          hour=df[c["hour"]], minute=df[c["minute"]]))
    df = df.set_index("timestamp")
    load = df[c["load_kw"]]
    volt_pv = (df[c["pv_w_per_module"]] / 1000) * modules
    existing = None
    pv_total = volt_pv
    if use_existing_pv:
        if c["existing_pv_kw"] not in df.columns:
            raise KeyError(f"use_existing_pv is true but column '{c['existing_pv_kw']}' is missing. "
                           f"Available columns: {list(df.columns)}")
        existing = df[c["existing_pv_kw"]].fillna(0.0)
        pv_total = pv_total + existing
    da = df[c["day_ahead_eur_kwh"]] * eur_to_local if c["day_ahead_eur_kwh"] in df.columns else None
    return Study(index=df.index, dt=dt, modules=modules, load=load, volt_pv=volt_pv, existing_pv=existing,
                 pv_total=pv_total, da_price=da)


def read_excel(path, **kwargs) -> Study:
    return from_frame(pd.read_excel(path), **kwargs)
