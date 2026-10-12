"""Solve a network and run a whole scenario in one call."""
import warnings

from .blocks import add_custom_constraints
from .results import check_balances, extract_results, summarise
from .sizing import resolve_sizes


def check_co2_capacity(n):
    """Feasibility hint: can the fixed-size units feeding the co2 bus cover the CO2 demand peak?
    Skipped if one of them has an optimised size."""
    if "GH CO2 demand" not in n.loads.index:
        return
    cap = 0.0
    for _, link in n.links.iterrows():
        for k, eff in (("1", "efficiency"), ("2", "efficiency2"), ("3", "efficiency3")):
            if link.get(f"bus{k}") == "co2":
                if link.p_nom_extendable:
                    return
                cap += link.p_nom * link[eff]
    peak = n.loads_t.p_set["GH CO2 demand"].max()
    if cap < peak:
        warnings.warn(f"Units feeding the CO2 bus can deliver max {cap * 1e3:.0f} kg CO2/h but peak demand is "
                      f"{peak * 1e3:.0f} kg/h -> expect unserved CO2.")


def solve(n, P, verbose=True):
    check_co2_capacity(n)
    status, condition = n.optimize(solver_name=P.solver_name,
                                   extra_functionality=lambda n, snapshots: add_custom_constraints(n, P),
                                   log_to_console=False,            # set True to see the solver log
                                   include_objective_constant=False,
                                   **P.solver_options)
    if verbose:
        print(f"Solver status: {status} / {condition}")
    if status != "ok":
        raise RuntimeError("Optimisation did not finish successfully, check inputs and sizes.")
    if verbose:
        print(f"Objective (annual cost in the optimisation): {n.objective:,.0f} EUR")
    return n


def run_scenario(build, data, P, verbose=True):
    """build: a scenario's build(data, P, sizes) function. Returns (network, Results)."""
    sizes = resolve_sizes(data, P)
    n = build(data, P, sizes)
    solve(n, P, verbose=verbose)
    r = extract_results(n, data, P)
    check_balances(r, verbose=verbose)
    return n, summarise(n, r, data, P, sizes)
