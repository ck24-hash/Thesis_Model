"""External CO2 supply: liquid CO2 bought and delivered to the greenhouse, kg per hour, at the CO2 price of the block's
input file (per kg, any regular step: an hourly or daily price curve over the year is fine; a monthly one is not
converted) or at a fixed price. It feeds the
CO2 bus next to the boiler's flue gas, so at each step the optimisation buys CO2 or burns gas for it, whichever costs
less (gas also gives heat, worth something when the greenhouse needs it). With it, the CO2 demand must be met.

Its CO2 is not counted in the site's emissions: it is produced elsewhere (thesis.md A21)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pypsa

from common import parameters as P
from elements.greenhouse.block import CO2_BUS

ID = "external_co2"
CARRIERS = {"in": [], "out": ["co2"]}
COLUMNS = [dict(role="co2_price_eur_kg", column="CO2 price (EUR/kg)", about="price of bought CO2 per kg",
                unit="EUR/kg", kind="price", needed="unless a fixed price is set")]
OWNS = {"external_co2": None}
PARAMS_DIR = Path(__file__).resolve().parent / "params"
GENERATOR = "co2_bought"


def load_params(market: dict, currency: str, overrides: dict | None = None, fx: dict | None = None) -> dict:
    return P.finish({"external_co2": P.shared(PARAMS_DIR / "external_co2", market["country"])}, overrides, currency, fx)


class ExternalCO2:
    def __init__(self, params: dict, index: pd.DatetimeIndex, price_eur_kg: pd.Series | None = None,
                 eur_to_local: float = 1.0):
        x = params["external_co2"]
        self.params = params
        if price_eur_kg is not None:
            if price_eur_kg.isna().any():
                raise ValueError(f"The CO2 price is missing at {int(price_eur_kg.isna().sum())} steps.")
            self.price = price_eur_kg * eur_to_local
        elif x.get("price_per_kg") is not None:
            self.price = pd.Series(float(x["price_per_kg"]), index=index)
        else:
            raise ValueError("The external CO2 supply needs a price: give it an input file with the CO2 price, or set "
                             "external_co2.price_per_kg in the overrides.")
        self.fixed_per_year = x.get("fixed_cost_per_year") or 0.0
        self.max_kg_h = x.get("max_kg_h")

    def add_to(self, n: pypsa.Network, demand_peak_kg_h: float) -> None:
        """A generator on the CO2 bus at the CO2 price, able to deliver max_kg_h (else the demand's peak)."""
        n.add("Generator", GENERATOR, bus=CO2_BUS, p_nom=max(self.max_kg_h or demand_peak_kg_h, 1.0), marginal_cost=0)
        n.generators_t.marginal_cost[GENERATOR] = self.price.reindex(n.snapshots)
