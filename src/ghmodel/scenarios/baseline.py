"""Baseline scenario: natural gas boiler + thermal storage + grid import (see docs/Scenarios.png)."""
import pypsa

from .. import blocks


def build(data, P, sizes):
    n = pypsa.Network(name="Baseline: NG boiler + thermal storage + grid")
    n.set_snapshots(data.index)                      # hourly, weighting = 1 h

    blocks.add_buses(n)
    blocks.add_greenhouse_loads(n, data)
    blocks.add_gas_supply(n, sizes)
    blocks.add_grid_import(n, sizes)
    blocks.add_ng_boiler(n, P, sizes)
    blocks.add_thermal_storage(n, P, sizes)
    blocks.add_sinks_and_slack(n, P)

    n.consistency_check()
    return n
