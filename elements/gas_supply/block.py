"""Gas supply (the fuel block): natural gas bought from the network, kWh per step at the gas price (lower heating
value), plus a carbon levy on the CO2 of the gas burnt. The price comes from the block's own input file (EUR/kWh,
converted to the market's currency like the day-ahead price), or from a fixed price parameter when there is no file.
Every block that burns gas takes it from the gas bus (today the gas boiler)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pypsa

from common import parameters as P

ID = "gas_supply"
CARRIERS = {"in": [], "out": ["gas"]}
COLUMNS = [dict(role="gas_price_eur_kwh", column="Gas price (EUR/kWh)", about="gas price per kWh (lower heating value)",
                unit="EUR/kWh", kind="price", needed="unless a fixed price is set")]
OWNS = {"gas": None}
PARAMS_DIR = Path(__file__).resolve().parent / "params"
GAS_BUS = "gas"
GENERATOR = "gas_supply"


def load_params(market: dict, currency: str, overrides: dict | None = None, fx: dict | None = None) -> dict:
    return P.finish({"gas": P.shared(PARAMS_DIR / "gas", market["country"])}, overrides, currency, fx)


class GasSupply:
    def __init__(self, params: dict, index: pd.DatetimeIndex, price_eur_kwh: pd.Series | None = None,
                 eur_to_local: float = 1.0):
        g = params["gas"]
        self.params = params
        if price_eur_kwh is not None:
            if price_eur_kwh.isna().any():
                raise ValueError(f"The gas price is missing at {int(price_eur_kwh.isna().sum())} steps.")
            self.price = price_eur_kwh * eur_to_local
        elif g.get("price_per_kwh") is not None:
            self.price = pd.Series(float(g["price_per_kwh"]), index=index)
        else:
            raise ValueError("The gas supply needs a price: give it an input file with the gas price, or set "
                             "gas.price_per_kwh in the overrides.")
        self.emission_factor = g["emission_factor_kg_per_kwh"]   # kg CO2 per kWh of gas
        self.levy_per_kg = g.get("co2_levy_per_kg", 0.0) or 0.0
        self.levy_per_kwh = self.levy_per_kg * self.emission_factor

    @property
    def cost_per_kwh(self) -> pd.Series:
        """What 1 kWh of gas costs at each step: price + carbon levy."""
        return self.price + self.levy_per_kwh

    def add_to(self, n: pypsa.Network, p_nom_kw: float) -> None:
        """The supply, able to deliver p_nom_kw (the most the gas users can burn)."""
        n.add("Bus", GAS_BUS, carrier="gas")
        n.add("Generator", GENERATOR, bus=GAS_BUS, p_nom=max(p_nom_kw, 1.0), marginal_cost=0)
        n.generators_t.marginal_cost[GENERATOR] = self.cost_per_kwh
