"""Scenario 1: gas CHP (heat, CO2, electricity) + backup boiler + thermal storage + grid import and export
(see docs/Scenarios.png). The CHP is dispatched before the backup boiler and grid import (chp_priority)."""
import pypsa

from .. import blocks


def build(data, P, sizes):
    n = pypsa.Network(name="S1: CHP + backup boiler + thermal storage + grid import/export")
    n.set_snapshots(data.index)                      # hourly, weighting = 1 h

    blocks.add_buses(n)
    blocks.add_greenhouse_loads(n, data)
    blocks.add_gas_supply(n, sizes)                  # one gas bus feeds CHP and backup boiler
    blocks.add_grid_import(n, sizes)
    blocks.add_grid_export(n, sizes)
    blocks.add_chp(n, P, sizes)
    blocks.add_ng_boiler(n, P, sizes)                # backup boiler (heat + CO2), same block as in the baseline
    blocks.add_thermal_storage(n, P, sizes)
    blocks.add_sinks_and_slack(n, P)
    blocks.add_chp_priority(n, P)                    # after boiler and grid: merit order CHP first

    n.consistency_check()
    return n
