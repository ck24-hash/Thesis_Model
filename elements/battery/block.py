"""Battery: a store with a charge and a discharge link on the site's electricity bus, sized in kWh bought. The
dispatch uses the state-of-charge window minus the reserve kept for ancillary services (tech.py; the reserve is per
country). Its price, replacements, subsidy, EMS and ancillary revenue are general items (general/commercial,
general/subsidies, general/ems). From elements/battery_reference: blocks/tech.py and the battery part of
engine/dispatch.py.

The size sweep and the payback study are in sizing.py and study.py."""
from __future__ import annotations

from pathlib import Path

import pypsa

from common import parameters as P
from common.network import BUS
from elements.battery.tech import Battery as Tech

ID = "battery"
CARRIERS = {"in": ["electricity"], "out": ["electricity"]}
COLUMNS: list = []
OWNS = {"tech": ["battery"], "ancillary": ["reserve"]}
PARAMS_DIR = Path(__file__).resolve().parent / "params"
STORE, CHARGER, DISCHARGER = "battery_store", "bat_charger", "bat_discharger"   # the battery model's names


def load_params(market: dict, currency: str, overrides: dict | None = None, fx: dict | None = None) -> dict:
    c = market["country"]
    params = {
        "ancillary": P.required(PARAMS_DIR / "ancillary" / f"{c}.json", "ancillary reserve"),
        "tech": P.shared(PARAMS_DIR / "tech", c),
    }
    return P.finish(params, overrides, currency, fx)


class Battery:
    def __init__(self, params: dict):
        self.params = params
        self.tech = Tech(params["tech"], params["ancillary"].get("reserve"))

    def add_to(self, n: pypsa.Network, size_kwh: float) -> None:
        """The battery the dispatch may use: size_kwh is the bought size; the ancillary reserve is left out."""
        t = self.tech
        n.add("Bus", "battery_bus", carrier="electricity")
        n.add("Store", STORE, bus="battery_bus", e_nom=t.dispatch_kwh(size_kwh), e_cyclic=True,
              standing_loss=t.self_discharge_per_hour, marginal_cost=0)
        n.add("Link", CHARGER, bus0=BUS, bus1="battery_bus", p_nom=t.dispatch_kw(size_kwh),
              efficiency=t.eff_store, marginal_cost=0)
        n.add("Link", DISCHARGER, bus0="battery_bus", bus1=BUS, p_nom=t.dispatch_kw(size_kwh),
              efficiency=t.eff_dispatch, marginal_cost=0)

    @staticmethod
    def results(n: pypsa.Network) -> dict:
        """battery_power (positive = discharging, negative = charging) and battery_soc (kWh in the dispatch window)."""
        return {"battery_power": -n.links_t.p1[DISCHARGER] - n.links_t.p0[CHARGER],
                "battery_soc": n.stores_t.e[STORE]}
