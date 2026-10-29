"""Heat storage (a hot water tank): heat from the heat bus is stored and given back later, sized in kWh of heat. It
charges from what gives heat to the heat bus (today the gas boiler) and discharges to the greenhouse (thesis.md A5).
A charge and a discharge efficiency, a most power in and out per kWh of size, and a heat loss through time. Its price,
O&M and life are in general/commercial.

Heat loss per hour, as a share of the heat stored (one value per step, PyPSA's standing loss):
    constant   the same share all year
    seasonal   one share per season: winter Dec-Feb, spring Mar-May, summer Jun-Aug, autumn Sep-Nov
    dynamic    from the outside temperature of the block's input file, step by step: the loss through the tank's
               walls follows the difference between the tank and the outside,
                   share_t = share at the reference x (T_store - T_out,t) / (T_store - T_ref), at least 0

The size sweep and its study are in sizing.py and study.py."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pypsa

from common import parameters as P
from elements.greenhouse.block import HEAT_BUS

ID = "thermal_storage"
CARRIERS = {"in": ["heat"], "out": ["heat"]}
COLUMNS = [dict(role="outside_temp_c", column="Outside temperature (C)", about="outside air temperature", unit="°C",
                kind="state", needed="with the dynamic heat loss")]
OWNS = {"thermal_storage": None}
PARAMS_DIR = Path(__file__).resolve().parent / "params"
BUS, STORE, CHARGER, DISCHARGER = "heat_store_bus", "heat_store", "heat_charger", "heat_discharger"
LOSS_MODES = ("constant", "seasonal", "dynamic")
SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}


def load_params(market: dict, currency: str, overrides: dict | None = None, fx: dict | None = None) -> dict:
    return P.finish({"thermal_storage": P.shared(PARAMS_DIR / "thermal_storage", market["country"])},
                    overrides, currency, fx)


def loss_per_hour(loss: dict, index: pd.DatetimeIndex, outside_temp_c: pd.Series | None = None) -> pd.Series:
    """The share of the stored heat lost per hour, at each step, for the loss mode of `loss`."""
    mode = loss["mode"]
    if mode not in LOSS_MODES:
        raise ValueError(f"Unknown heat loss mode {mode!r}; use one of {', '.join(LOSS_MODES)}.")
    if mode == "constant":
        return pd.Series(float(loss["constant_per_hour"]), index=index)
    if mode == "seasonal":
        per_season = loss["seasonal_per_hour"]
        return pd.Series([float(per_season[SEASONS[m]]) for m in index.month], index=index)
    if outside_temp_c is None:
        raise ValueError("The dynamic heat loss needs the outside temperature: give the heat storage an input file "
                         f"with the column '{COLUMNS[0]['column']}'.")
    if outside_temp_c.isna().any():
        raise ValueError(f"The outside temperature is missing at {int(outside_temp_c.isna().sum())} steps.")
    d = loss["dynamic"]
    span = d["store_temp_c"] - d["ref_outside_temp_c"]
    if span <= 0:
        raise ValueError("The dynamic heat loss needs a store temperature above the reference outside temperature.")
    share = d["loss_per_hour_at_ref"] * (d["store_temp_c"] - outside_temp_c.reindex(index)) / span
    return share.clip(lower=0.0, upper=1.0)


class ThermalStorage:
    def __init__(self, params: dict, index: pd.DatetimeIndex, outside_temp_c: pd.Series | None = None):
        t = params["thermal_storage"]
        self.params = params
        self.eff_charge = t["charge_efficiency"]
        self.eff_discharge = t["discharge_efficiency"]
        self.power_per_kwh = t["power_kw_per_kwh"]
        self.loss_mode = t["loss"]["mode"]
        self.outside_temp = outside_temp_c
        self.loss_per_hour = loss_per_hour(t["loss"], index, outside_temp_c)

    def power_kw(self, size_kwh: float) -> float:
        """The most heat the tank takes in, and gives out, per hour."""
        return size_kwh * self.power_per_kwh

    def add_to(self, n: pypsa.Network, size_kwh: float) -> None:
        """A store on its own bus, a charging link from the heat bus and a discharging link back to it. The
        discharging link's limit is on the store side, so the heat given out is at most power_kw."""
        power = self.power_kw(size_kwh)
        n.add("Bus", BUS, carrier="heat")
        n.add("Store", STORE, bus=BUS, e_nom=size_kwh, e_cyclic=True,
              standing_loss=self.loss_per_hour.reindex(n.snapshots), marginal_cost=0)
        n.add("Link", CHARGER, bus0=HEAT_BUS, bus1=BUS, p_nom=power, efficiency=self.eff_charge, marginal_cost=0)
        n.add("Link", DISCHARGER, bus0=BUS, bus1=HEAT_BUS, p_nom=power / self.eff_discharge,
              efficiency=self.eff_discharge, marginal_cost=0)

    @staticmethod
    def results(n: pypsa.Network) -> dict:
        """storage_charge (heat taken from the heat bus, kW), storage_discharge (heat given to it, kW), storage_soc
        (heat stored, kWh)."""
        return {"storage_charge": n.links_t.p0[CHARGER], "storage_discharge": -n.links_t.p1[DISCHARGER],
                "storage_soc": n.stores_t.e[STORE]}
