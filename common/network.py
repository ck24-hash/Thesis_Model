"""PyPSA pieces more than one block uses."""
from __future__ import annotations

import pandas as pd
import pypsa

BUS = "main"   # the site's electricity bus (the battery model's name, kept so the LP is the same)


def add_must_run(n: pypsa.Network, name: str, profile_kw: pd.Series, bus: str = BUS) -> None:
    """A generator that produces exactly `profile_kw` at each step: PV that cannot be curtailed."""
    p_nom = float(profile_kw.max())
    pu = (profile_kw / p_nom).clip(upper=1.0) if p_nom > 0 else profile_kw * 0.0
    n.add("Generator", name, bus=bus, p_nom=p_nom, marginal_cost=0)
    n.generators_t.p_max_pu[name] = pu
    n.generators_t.p_min_pu[name] = pu
