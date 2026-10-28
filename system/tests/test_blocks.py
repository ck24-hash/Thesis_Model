"""Checks of the blocks and the engine: python -m pytest system/tests -q (about 3 min).

The parameters and short battery studies are compared with the reference model (elements/battery_reference); the
electricity bus must balance at every step; each block reads its own input file."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from system import compare, dispatch, setup  # noqa: E402  (compare puts the reference model on the path)

import parameters as reference_parameters  # noqa: E402  (elements/battery_reference/parameters.py)

EXAMPLES = ROOT / "examples" / "battery"
BLOCK_EXAMPLES = ROOT / "examples" / "blocks"
MARKETS = [{"country": "CH", "region": "GE", "utility": "SIG", "year": 2026},
           {"country": "NL", "region": "WestlandInfra", "utility": "MS", "year": 2026},
           {"country": "FR", "region": "HTA", "utility": "Reference", "year": 2025}]


def without_about(d):
    return {k: without_about(v) for k, v in d.items() if k != "_about"} if isinstance(d, dict) else d


def short(case: dict) -> dict:
    """The case with one battery size, to keep the test quick."""
    sizing = {"sweep_kwh": [100], "cap_at_subsidy_size": False}
    if "blocks" in case:
        return {**case, "blocks": {**case["blocks"], "battery": {"sizing": sizing}}}
    return {**case, "sizing": sizing}


@pytest.mark.parametrize("market", MARKETS, ids=lambda m: m["country"])
@pytest.mark.parametrize("business_model", ["direct_sales", "eaas"])
def test_parameters_as_reference(market, business_model):
    overrides = {"tech": {"battery": {"c_rate": 0.4}, "module_wp": 150}, "finance": {"pv_life_yr": 20},
                 "ancillary": {"rate_per_kw_year": 0}, "tariff": {"battery_export": "any"},
                 "capex": {"pv_per_wp": {"amount": 2.0}}}
    for ov in (None, overrides):
        ours = setup.parameters(market, business_model, ov)
        ref = reference_parameters.load(market["country"], market["region"], market["utility"], market["year"],
                                        business_model=business_model, overrides=ov)
        assert without_about(ours) == without_about(ref)


def test_overrides_go_to_their_block():
    owners = setup.OWNERS
    split = setup.P.split_overrides({"tech": {"battery": {"c_rate": 0.4}, "module_wp": 150}, "ems": {"capex": 0},
                                     "tariff": {"export": {"per_kwh": 0.1}}, "capex": {"pv_per_wp": 2},
                                     "ancillary": {"rate_per_kw_year": 0, "reserve": {"frac": 0}},
                                     "subsidies": {"pv": {"frac": 0.3}}}, owners)
    assert split["battery"] == {"tech": {"battery": {"c_rate": 0.4}}, "ancillary": {"reserve": {"frac": 0}}}
    assert split["voltiris"] == {"tech": {"module_wp": 150}}
    assert split["grid"] == {"tariff": {"export": {"per_kwh": 0.1}}}
    assert split["commercial"] == {"capex": {"pv_per_wp": 2}, "ancillary": {"rate_per_kw_year": 0}}
    assert split["subsidies"] == {"subsidies": {"pv": {"frac": 0.3}}}
    assert split["ems"] == {"ems": {"capex": 0}}
    with pytest.raises(KeyError, match="Unknown override group"):
        setup.P.split_overrides({"heat": {}}, owners)
    with pytest.raises(KeyError, match="Unknown override tech.cop"):
        setup.P.split_overrides({"tech": {"cop": 3}}, owners)


def test_blocks_not_built_or_missing():
    case = setup.load_case(EXAMPLES / "case_example_CH.json")
    index, inputs, _ = setup.read_inputs(case, setup.excel_reader())
    with pytest.raises(ValueError, match="Not built yet: heat_pump"):
        setup.System(index, inputs, case["market"], {"greenhouse": {}, "grid": {}, "heat_pump": {}})
    with pytest.raises(ValueError, match="missing: grid"):
        setup.System(index, inputs, case["market"], {"greenhouse": {}})


def test_separate_files():
    """Each block reads its own file; the hourly existing PV file is brought to 15 min with its energy kept; a file
    that misses time steps of the load file is refused."""
    case = setup.load_case(BLOCK_EXAMPLES / "case_blocks_CH_existing_pv.json")
    read = setup.excel_reader()
    index, inputs, steps = setup.read_inputs(case, read)
    assert {k: v["step_minutes"] for k, v in steps.items()} == {"greenhouse": 15, "voltiris": 15, "existing_pv": 60,
                                                               "grid": 15}
    assert len(index) == 35040 and all(s.index.equals(index) for s in inputs.values())
    hourly = read(case["blocks"]["existing_pv"]["input_file"])["Current PV feed-in (kW)"]
    assert abs(inputs["existing_pv_kw"].sum() * 0.25 - hourly.sum()) < 1e-6
    short_file = case["blocks"]["voltiris"]["input_file"]

    def truncated(path):
        return read(path).iloc[:-96] if path == short_file else read(path)
    with pytest.raises(ValueError, match="misses 96 of the 35040 time steps"):
        setup.read_inputs(case, truncated)


def test_electricity_balance_every_step():
    s = setup.build(json.loads((BLOCK_EXAMPLES / "case_blocks_CH_existing_pv.json").read_text()), BLOCK_EXAMPLES)
    n = dispatch.solve(s, "B", battery_kwh=200)
    res = dispatch.results(n, s)
    residual = res["pv"] + res["grid_import"] - res["grid_export"] + res["battery_power"] - res["load"]
    assert residual.abs().max() < 1e-6
    assert (res["pv"] - s.pv_total).abs().max() < 1e-9


@pytest.mark.parametrize("path", [EXAMPLES / "case_example_CH.json", EXAMPLES / "case_example_NL.json",
                                  BLOCK_EXAMPLES / "case_blocks_CH_existing_pv.json"], ids=lambda p: p.stem)
def test_short_study_as_reference(path):
    """One battery size, the whole study: the summary and every table equal to the last digit."""
    case = short(json.loads(path.read_text()))
    ref = compare.run_reference(case, path.parent, "t")
    new, _ = compare.blocks.run(case, path.parent, "t", log=lambda *a, **k: None)
    assert compare.differences(ref, new) == []
