# Block 7: Custom constraints (`add_custom_constraints`)

**Function**: `add_custom_constraints(n, P)` in [`blocks.py`](../../src/ghmodel/blocks.py)

## Purpose
Adds equations that PyPSA has no component attribute for. It does not add any component. `workflow.solve()` calls it
automatically after PyPSA has built the optimisation model and before HiGHS solves it (`extra_functionality`).
Each constraint is only added if the components it needs exist, so the function can be used in every scenario.

## Constraints currently included

### Storage power linked to storage capacity (only when `OPTIMISE_TES = True`)
When the storage capacity $S$ is a decision variable, the charge and discharge links are also extendable and have no
cost of their own, so without this constraint their power would be unlimited. With $h$ = `tes_hours_at_full_power`:

$$h \cdot P^{S}_{ch} \le S \qquad\qquad h \cdot \eta_d \cdot P^{S}_{dis} \le S$$

($P^{S}_{dis}$ is on the store side, so $\eta_d P^{S}_{dis}$ is the maximum heat delivered.) Names in the model:
`TES-charge-power-per-capacity`, `TES-discharge-power-per-capacity`.

With fixed sizes the same rule is applied directly to the storage power in `sizing.py`, so no extra equation is needed.

## Parameters
| Parameter | Default | Unit | Meaning |
|---|---|---|---|
| `tes_hours_at_full_power` | 4.0 | h | minimum time to fully charge or discharge at maximum power; `None` = no constraint `[placeholder]` |
| `tes_eta_discharge` | 0.98 | – | shared with block 6 |

## Inputs / outputs
Inputs: the PyPSA model variables `Store-e_nom` and `Link-p_nom`. Outputs: the optimised link sizes
`n.links.p_nom_opt` for `TES charge` and `TES discharge` respect the limit.

## Tests
`test_storage_optimisation_is_not_worse_than_fixed_size`.

## Notes for S1 to S4
This is the place for future constraints that link component sizes or need custom equations, for example
a battery power/energy ratio, a heat-pump source limit (heat drawn ≤ data-center heat available), or a minimum
self-sufficiency share.
