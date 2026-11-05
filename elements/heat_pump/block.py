"""Heat pump: electricity in, heat out, sized in kW of heat. Without a data center (not built yet) its heat source is
the outside air: an air-source heat pump (scenario S2). Per kWh of electricity it gives COP kWh of heat to the heat
bus, the COP being (cop.mode):

    constant   cop.nominal all year
    dynamic    from the outside temperature of the block's input file, step by step: the COP follows the Carnot COP
               of lifting heat from the outside air to the supply temperature, scaled to cop.nominal at the reference
               outside temperature (a constant share of the Carnot COP):
                   COP_t = cop.nominal x (T_supply - T_ref) / (T_supply - T_out,t)

Its size Q (kW of heat) is the most heat it gives at any step, whatever the COP, so the electricity it draws is at most
Q / COP_t (the most of all at the lowest COP of the year). It runs whenever that is the cheapest way to meet the heat
demand: the optimisation weighs its electricity against the gas of the boiler step by step. Heat it gives beyond the
demand is released, as for the boiler. Its price, O&M and life are in general/commercial; it is sized in the joint
sizing (system/joint.py), or fixed at a given size."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pypsa

from common import parameters as P
from common.network import BUS
from elements.greenhouse.block import HEAT_BUS

ID = "heat_pump"
CARRIERS = {"in": ["electricity"], "out": ["heat"]}
COLUMNS = [dict(role="hp_outside_temp_c", column="Outside temperature (C)", about="outside air temperature, the "
                "heat pump's source", unit="°C", kind="state", needed="with the dynamic COP")]
OWNS = {"heat_pump": None}
PARAMS_DIR = Path(__file__).resolve().parent / "params"
LINK = "heat_pump"
COP_MODES = ("constant", "dynamic")


def load_params(market: dict, currency: str, overrides: dict | None = None, fx: dict | None = None) -> dict:
    return P.finish({"heat_pump": P.shared(PARAMS_DIR / "heat_pump", market["country"])}, overrides, currency, fx)


def cop_series(hp: dict, index: pd.DatetimeIndex, outside_temp_c: pd.Series | None = None) -> pd.Series:
    """The COP at each step, for the COP mode of `hp` (the block's parameters)."""
    cop = hp["cop"]
    mode, nominal = cop["mode"], float(cop["nominal"])
    if mode not in COP_MODES:
        raise ValueError(f"Unknown COP mode {mode!r}; use one of {', '.join(COP_MODES)}.")
    if nominal <= 0:
        raise ValueError("The heat pump's COP must be above 0.")
    if mode == "constant":
        return pd.Series(nominal, index=index)
    if outside_temp_c is None:
        raise ValueError("The dynamic COP needs the outside temperature: give the heat pump an input file with the "
                         f"column '{COLUMNS[0]['column']}'.")
    temp = outside_temp_c.reindex(index)
    if temp.isna().any():
        raise ValueError(f"The outside temperature is missing at {int(temp.isna().sum())} steps.")
    supply, ref = float(hp["supply_temp_c"]), float(cop["ref_outside_temp_c"])
    if supply <= ref:
        raise ValueError("The heat pump's supply temperature must be above its reference outside temperature.")
    if (temp >= supply).any():
        raise ValueError(f"The outside temperature reaches the supply temperature ({supply:g} °C): the dynamic COP "
                         "cannot be computed there.")
    return nominal * (supply - ref) / (supply - temp)


class HeatPump:
    def __init__(self, params: dict, index: pd.DatetimeIndex, outside_temp_c: pd.Series | None = None):
        h = params["heat_pump"]
        self.params = params
        self.supply_temp_c = h["supply_temp_c"]
        self.cop_mode = h["cop"]["mode"]
        self.cop_nominal = h["cop"]["nominal"]
        self.ref_outside_temp_c = h["cop"]["ref_outside_temp_c"]
        self.outside_temp = outside_temp_c
        self.cop = cop_series(h, index, outside_temp_c)
        self.cop_min = float(self.cop.min())

    def electricity_kw(self, size_kw_th: float) -> float:
        """The most electricity it draws: its heat size at the lowest COP of the year."""
        return size_kw_th / self.cop_min

    def add_to(self, n: pypsa.Network, size_kw_th: float) -> None:
        """A link from the electricity bus to the heat bus with the COP of each step as its efficiency. Its limit is
        on the electricity side, Q / lowest COP, reduced at each step to Q / COP_t, so the heat is at most Q."""
        n.add("Link", LINK, bus0=BUS, bus1=HEAT_BUS, p_nom=self.electricity_kw(size_kw_th), efficiency=1.0,
              marginal_cost=0)
        n.links_t.efficiency[LINK] = self.cop.reindex(n.snapshots)
        n.links_t.p_max_pu[LINK] = (self.cop_min / self.cop).reindex(n.snapshots)

    @staticmethod
    def results(n: pypsa.Network) -> dict:
        """hp_heat (heat given to the heat bus, kW), hp_electricity (electricity drawn, kW)."""
        return {"hp_heat": -n.links_t.p1[LINK], "hp_electricity": n.links_t.p0[LINK]}
