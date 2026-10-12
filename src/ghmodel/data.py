"""Reading and checking the hourly Excel input, plus a synthetic dummy dataset for testing."""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DAILY_TOTAL_COLUMNS, INPUT_COLUMNS, OPTIONAL_COLUMNS, Params


def make_dummy_input(path, sheet="hourly", year=2023, seed=42, export_price=False):
    # Synthetic 1 ha greenhouse dataset (NOT real data), only to test the notebook.
    # export_price=True adds the column needed for grid export (S1+); the other columns stay identical.
    rng = np.random.default_rng(seed)
    idx = pd.date_range(f"{year}-01-01", periods=8760, freq="h")
    doy = idx.dayofyear.to_numpy()
    hod = idx.hour.to_numpy()
    n_days = doy.max()

    # daily weather noise (AR(1)) repeated over the 24 h of each day
    def daily_ar(sigma, phi=0.8):
        x = np.zeros(n_days)
        for i in range(1, n_days):
            x[i] = phi * x[i - 1] + rng.normal(0, sigma)
        return x[doy - 1]

    # outdoor temperature [degC]
    t_out = (10.5 - 8.0 * np.cos(2 * np.pi * (doy - 20) / 365)
             - 3.0 * np.cos(2 * np.pi * (hod - 4) / 24)
             + daily_ar(2.0) + rng.normal(0, 0.5, len(idx)))

    # normalised solar profile [0-1]
    day_len = 12 + 4.0 * np.sin(2 * np.pi * (doy - 80) / 365)
    sun = np.clip(np.sin(np.pi * (hod + 0.5 - (12 - day_len / 2)) / day_len), 0, None)
    sun[(hod + 0.5 < 12 - day_len / 2) | (hod + 0.5 > 12 + day_len / 2)] = 0
    cloud = np.clip(0.75 + 0.35 * daily_ar(0.5, 0.3), 0.2, 1.0)
    solar = sun * (0.3 + 0.7 * (day_len - 8) / 8) * cloud

    # greenhouse heat demand [kW]: transmission/ventilation losses minus solar gains
    t_set = np.where(sun > 0, 20.0, 17.0)
    heat = np.clip(48 * (t_set - t_out) - 550 * solar, 0, None)

    # electricity demand [kW]: fans, pumps, screens, control
    elec = 35 + 40 * solar + rng.normal(0, 3, len(idx))

    # CO2 dosing demand [kg/h]: only in light hours, reduced when vents are open (warm)
    vent_open = np.clip((t_out - 14) / 8, 0, 1)
    co2 = 150 * solar ** 0.7 * (1 - 0.55 * vent_open) * rng.normal(1, 0.05, len(idx))
    co2 = np.clip(co2, 0, None)

    # prices (dummy)
    gas_price = np.clip(45 + 8 * np.cos(2 * np.pi * (doy - 15) / 365) + daily_ar(1.5, 0.95), 15, None)
    elec_price = (100 + 25 * np.exp(-((hod - 19) / 2.5) ** 2) + 15 * np.exp(-((hod - 8) / 2) ** 2)
                  - 30 * solar + daily_ar(10, 0.7))
    elec_price = np.clip(elec_price, 20, None)

    df = pd.DataFrame({
        "timestamp": idx,
        "heat_demand_kW": heat,
        "elec_demand_kW": elec,
        "co2_demand_kg_h": co2,
        "gas_price_EUR_per_MWh": gas_price,
        "elec_price_EUR_per_MWh": elec_price,
    })
    units = ["datetime (hourly, no DST gaps)", "kW thermal", "kW electric", "kg CO2 per hour",
             "EUR per MWh fuel (LHV, all-in)", "EUR per MWh (all-in import price)"]
    if export_price:
        # wholesale-like price, always below the import price (no import/export arbitrage)
        exp = 0.7 * elec_price - 10 + rng.normal(0, 5, len(idx))
        df["elec_export_price_EUR_per_MWh"] = np.clip(exp, 0, elec_price - 5)
        units.append("EUR per MWh paid for exported electricity")
    readme = pd.DataFrame({
        "column": df.columns,
        "unit": units,
        "comment": ["SYNTHETIC DUMMY DATA, replace with your own"] + [""] * (len(units) - 1),
    })
    with pd.ExcelWriter(path) as xw:
        df.to_excel(xw, sheet_name=sheet, index=False)
        readme.to_excel(xw, sheet_name="README", index=False)
    return df



def load_inputs(path, sheet_name="hourly", time_col="timestamp", start_timestamp="2023-01-01 00:00",
                params=None, input_columns=INPUT_COLUMNS, optional_columns=OPTIONAL_COLUMNS):
    """Read the Excel sheet, convert to internal units (MW, t/h, EUR/MWh) and run basic checks.

    Hourly or daily rows are accepted. Daily rows are converted to hourly with daily_to_hourly().
    Returns a DataFrame with an hourly DatetimeIndex named 'snapshot'.
    """
    params = params or Params()
    raw = pd.read_excel(path, sheet_name=sheet_name)
    raw.columns = [str(c).strip() for c in raw.columns]

    missing = [col for col, _ in input_columns.values() if col not in raw.columns]
    if missing:
        raise KeyError(f"Columns missing in sheet '{sheet_name}': {missing}\nFound: {list(raw.columns)}")

    # resolution from the number of rows: 365/366 -> daily, 8760/8784 -> hourly (366 and 8784 = leap year).
    # Other row counts: decided from the timestamps (hourly if there is no time column).
    n_rows = len(raw)
    step = {365: "D", 366: "D", 8760: "h", 8784: "h"}.get(n_rows)
    has_time = time_col is not None and time_col in raw.columns
    if has_time:
        index = pd.DatetimeIndex(pd.to_datetime(raw[time_col]), name="snapshot")
    else:
        index = pd.date_range(start_timestamp, periods=n_rows, freq=step or "h", name="snapshot")

    steps = pd.Series(index).diff().dropna().unique()
    found = ("D" if steps[0] == pd.Timedelta(days=1) else "h" if steps[0] == pd.Timedelta(hours=1) else None) \
        if len(steps) == 1 else None
    if found is None:
        raise ValueError("Timestamps must be strictly hourly or strictly daily, without gaps or duplicates "
                         "(check daylight-saving shifts). Found steps: " + str(steps))
    if step is not None and found != step:
        raise ValueError(f"{n_rows} rows means {'daily' if step == 'D' else 'hourly'} data, but the timestamps are "
                         f"{'daily' if found == 'D' else 'hourly'}.")
    daily = found == "D"

    # leap-year check: a full year must end exactly one calendar year after its first timestamp
    if step is not None and index[0] + pd.DateOffset(years=1) - pd.Timedelta(1, unit=step) != index[-1]:
        warnings.warn(f"{n_rows} rows is a {'leap' if n_rows in (366, 8784) else 'non-leap'} year, but the data run "
                      f"from {index[0]} to {index[-1]}, which is not one calendar year"
                      + ("" if has_time else " (set START_TIMESTAMP to a matching year)") + ".")

    # convert to internal units
    data = pd.DataFrame(index=index)
    for name, (col, factor) in input_columns.items():
        data[name] = raw[col].to_numpy(dtype=float) * factor
    for name, (col, factor) in optional_columns.items():
        if col in raw.columns:
            data[name] = raw[col].to_numpy(dtype=float) * factor

    if daily:
        data = daily_to_hourly(data)
        warnings.warn(f"Daily input detected ({len(index)} days): demand columns are read as daily totals "
                      "(kWh/day, kg/day) and spread evenly over 24 h; prices are repeated each hour. "
                      "Flat profile within the day: no day/night pattern (assumption).")

    if len(data) not in (8760, 8784):
        warnings.warn(f"Input has {len(data)} hours, not a full year (8760 or 8784): "
                      "annual totals and costs will not be annual values.")

    # checks
    nan_count = data.isna().sum()
    if nan_count.any():
        raise ValueError(f"NaN values found in input data:\n{nan_count[nan_count > 0]}")
    for c in ["heat_demand_MW", "elec_demand_MW", "co2_demand_t_h"]:
        if (data[c] < 0).any():
            raise ValueError(f"Negative values in {c}")

    if "grid_ef_t_MWh" not in data:
        data["grid_ef_t_MWh"] = params.grid_ef()   # constant (explicit or country default) if no hourly column given
    return data


def daily_to_hourly(daily, total_columns=DAILY_TOTAL_COLUMNS):
    """Daily rows -> hourly rows. Daily totals (total_columns) are divided by 24, so each hour gets the
    daily average; all other columns (prices, emission factors) keep the daily value in every hour."""
    index = pd.date_range(daily.index[0], periods=24 * len(daily), freq="h", name="snapshot")
    hourly = pd.DataFrame(np.repeat(daily.to_numpy(), 24, axis=0), index=index, columns=daily.columns)
    cols = [c for c in total_columns if c in hourly]
    hourly[cols] = hourly[cols] / 24
    return hourly


def input_overview(data, area_m2):
    """Small table with annual totals and peaks of the input series."""
    return pd.DataFrame({
        "Value": [data.heat_demand_MW.sum(), data.heat_demand_MW.max(),
                  data.heat_demand_MW.sum() * 1e3 / area_m2,
                  data.elec_demand_MW.sum(), data.elec_demand_MW.max(),
                  data.co2_demand_t_h.sum(), data.co2_demand_t_h.max() * 1e3,
                  data.gas_price_EUR_MWh.mean(), data.elec_price_EUR_MWh.mean()],
        "Unit": ["MWh/y", "MW", "kWh/m2/y", "MWh/y", "MW", "t/y", "kg/h", "EUR/MWh", "EUR/MWh"],
    }, index=["Heat demand (annual)", "Heat demand (peak)", "Heat demand (specific)",
              "Electricity demand (annual)", "Electricity demand (peak)",
              "CO2 demand (annual)", "CO2 demand (peak)",
              "Gas price (mean)", "Electricity price (mean)"])
