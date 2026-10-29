"""Gas boiler: gas in, heat and flue gas CO2 out, sized in kW of heat. Per kWh of gas: efficiency kWh of heat to the
heat bus, and emission factor x usable share kg of CO2 to the CO2 bus (the rest of the CO2 is vented; all of it is
emitted). Heat it gives beyond the demand is released (system/dispatch.py), so it may run for CO2 alone. Its price,
O&M and life are in general/commercial.

The size sweep and its study are in sizing.py and study.py."""
from __future__ import annotations

from pathlib import Path

import pypsa

from common import parameters as P
from elements.gas_supply.block import GAS_BUS
from elements.greenhouse.block import CO2_BUS, HEAT_BUS

ID = "ng_boiler"
CARRIERS = {"in": ["gas"], "out": ["heat", "co2"]}
COLUMNS: list = []
OWNS = {"boiler": None}
PARAMS_DIR = Path(__file__).resolve().parent / "params"
LINK = "boiler"


def load_params(market: dict, currency: str, overrides: dict | None = None, fx: dict | None = None) -> dict:
    return P.finish({"boiler": P.shared(PARAMS_DIR / "boiler", market["country"])}, overrides, currency, fx)


class Boiler:
    def __init__(self, params: dict):
        b = params["boiler"]
        self.params = params
        self.efficiency = b["efficiency"]
        self.co2_use_frac = b["co2_use_frac"]

    def gas_kw(self, size_kw_th: float) -> float:
        """The most gas the boiler burns: its heat size / efficiency."""
        return size_kw_th / self.efficiency

    def add_to(self, n: pypsa.Network, size_kw_th: float, emission_factor: float, var_om_per_kwh_heat: float) -> None:
        """A link from the gas bus to the heat bus and the CO2 bus; its variable O&M is per kWh of heat, so per kWh of
        gas it is that x efficiency."""
        n.add("Link", LINK, bus0=GAS_BUS, bus1=HEAT_BUS, bus2=CO2_BUS, p_nom=self.gas_kw(size_kw_th),
              efficiency=self.efficiency, efficiency2=emission_factor * self.co2_use_frac,
              marginal_cost=var_om_per_kwh_heat * self.efficiency)
