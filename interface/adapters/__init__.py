"""Run types: one adapter per model the interface can run. Each adapter says which blocks it needs and which it can
take (BLOCKS_REQUIRED, BLOCKS_ALLOWED); the system chosen in the page picks the adapter, and when several fit, the
page asks which (the case's system.run_type). A new model is a new module here, added to ADAPTERS. The first one
that fits is the default."""
from __future__ import annotations

from interface.adapters import battery_study, system_study

ADAPTERS = {system_study.ID: system_study, battery_study.ID: battery_study}


def fits(adapter, blocks) -> bool:
    chosen = set(blocks)
    one_of = getattr(adapter, "BLOCKS_ONE_OF", None)   # at least one of these, when the adapter says so
    return (set(adapter.BLOCKS_REQUIRED) <= chosen <= set(adapter.BLOCKS_ALLOWED)
            and (not one_of or bool(chosen & set(one_of))))


def for_blocks(blocks: list[str]):
    """The first adapter that can run this set of blocks, or (None, why not)."""
    chosen = set(blocks)
    reasons = []
    for adapter in ADAPTERS.values():
        if fits(adapter, chosen):
            return adapter, None
        missing = [b for b in adapter.BLOCKS_REQUIRED if b not in chosen]
        one_of = getattr(adapter, "BLOCKS_ONE_OF", None)
        if one_of and not chosen & set(one_of):
            missing.append(" or ".join(one_of))
        extra = sorted(chosen - set(adapter.BLOCKS_ALLOWED))
        reasons.append(f"{adapter.NAME}: " + "; ".join(
            ([f"needs {', '.join(missing)}"] if missing else []) + ([f"cannot run {', '.join(extra)}"] if extra else [])))
    return None, "No model can run this system yet. " + " / ".join(reasons)


def for_case(case: dict):
    """The adapter for a case file: the run type it names if that one fits its blocks, else the first that fits. A
    case without a system (an older battery case) has the battery study's blocks."""
    system = case.get("system") or {}
    blocks = system.get("blocks") or battery_study.BLOCKS_ALLOWED
    wanted = ADAPTERS.get(system.get("run_type"))
    if wanted is not None and fits(wanted, blocks):
        return wanted
    adapter, why = for_blocks(blocks)
    if adapter is None:
        raise ValueError(why)
    return adapter
