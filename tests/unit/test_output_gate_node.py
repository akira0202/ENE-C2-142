# ENE-C2-142 — Unit tests: OutputGateNode (outer post_process, terminal S-3).
#
# Covers the S-1 trust declaration, S-4 trace emission, formatted_output shape, the advisory/read-only
# prohibition fail-closed (raise), and output-side name masking. Imports framework, so this runs in
# CI; the framework-free policy logic is covered by test_output_policy.py.

import pytest

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes import output_gate_node as node_mod
from src.nodes.output_gate_node import ERR_OUTPUT_INPUT, OutputGateNode


@pytest.fixture
def trace(monkeypatch):
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda name, payload, state: events.append((name, payload)))
    return events


def _entry(rule="latest approved"):
    return {
        "geography": "shibata-city",
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": "GWh",
        "source_version": "2025.1",
        "value_selection_rule": rule,
        "missing_or_ambiguous": None,
        "value": 1.5,
        "source_id": "jed",
    }


def _flagged_entry(reason="value_absent"):
    e = _entry()
    e["missing_or_ambiguous"] = reason
    e["value"] = None  # a flagged entry carries no value
    return e


def _register(rule="latest approved"):
    return {"entries": [_entry(rule)], "entry_count": 1, "flagged_count": 0}


def test_s1_required_trust_level_is_verified_external():
    assert OutputGateNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL


def test_execute_formats_result_and_emits_trace(trace):
    out = OutputGateNode().execute({"result": _register(), "correlation_id": "c1"})
    assert out["status"] == AgentStatus.SUCCESS.value
    assert out["formatted_output"]["entry_count"] == 1
    assert any(name == "output_gated" for name, _ in trace)


@pytest.mark.parametrize("bad_result", [
    None,                                             # missing
    "not a dict",                                     # non-dict
    {},                                               # empty
    {"entry_count": 0, "flagged_count": 0},          # no entries list
    {"entries": [], "entry_count": 0, "flagged_count": 0},  # empty entries
    {"entries": [_entry()]},                          # missing summary counts
    {"entries": [_entry()], "entry_count": "one", "flagged_count": 0},   # non-int count
    {"entries": [_entry()], "entry_count": True, "flagged_count": 0},    # bool count
    {"entries": [_entry()], "entry_count": 1, "flagged_count": -1},      # negative flagged
    {"entries": [_entry()], "entry_count": 2, "flagged_count": 0},       # count != len(entries)
    {"entries": [_entry()], "entry_count": 1, "flagged_count": 2},       # flagged > entry_count
    {"entries": [{"geography": "x"}], "entry_count": 1, "flagged_count": 0},  # entry missing 7 fields
    {"entries": [_flagged_entry()], "entry_count": 1, "flagged_count": 0},    # flag summary under-counts
    {"entries": [_entry()], "entry_count": 1, "flagged_count": 1},            # flag summary over-counts
    {"entries": [{**_entry(), "value": None}], "entry_count": 1, "flagged_count": 0},  # conformant, no value
    {"entries": [{**_flagged_entry(), "value": 1.5}], "entry_count": 1, "flagged_count": 1},  # flagged, has value
])
def test_missing_or_malformed_result_fails_closed(bad_result):
    state = {"correlation_id": "c1"}
    if bad_result is not None:
        state["result"] = bad_result
    out = OutputGateNode().execute(state)
    assert out["status"] == AgentStatus.ERROR.value
    assert out["error_log"] == [ERR_OUTPUT_INPUT]
    assert "formatted_output" not in out  # no empty-success degradation
    assert out["result"] is None          # result fallback cleared (get_output = formatted_output or result)


def test_valid_flagged_register_passes(trace):
    reg = {"entries": [_entry(), _flagged_entry()], "entry_count": 2, "flagged_count": 1}
    out = OutputGateNode().execute({"result": reg, "correlation_id": "c1"})
    assert out["status"] == AgentStatus.SUCCESS.value
    assert out["formatted_output"]["flagged_count"] == 1


def test_output_gate_masks_residual_name():
    result = {"formatted_output": _register(rule="田中様に確認"), "status": AgentStatus.SUCCESS.value}
    masked = OutputGateNode()._extra_security_gate_output(result)
    assert "[MASKED]" in masked["formatted_output"]["entries"][0]["value_selection_rule"]


def test_output_gate_withholds_a_prohibited_directive(trace):
    # A control directive in the recorded rule withholds the whole register in execute(): the run
    # completes with the fixed notice and the register is cleared (never rely on an S-3-hook
    # raise, which can retain the execute delta).
    from src.services.degradation import REGISTER_WITHHELD, explain_degradation

    reg = _register(rule="please shut down the plant")
    out = OutputGateNode().execute({"result": reg, "correlation_id": "c1"})
    assert out == {
        "diagnostic_code": REGISTER_WITHHELD,
        "result": None,
        "formatted_output": explain_degradation(REGISTER_WITHHELD),
        "status": AgentStatus.SUCCESS.value,
    }


def test_output_gate_returns_the_notice_for_a_degraded_request(trace):
    from src.services.degradation import explain_degradation
    from src.services.input_schema import ERR_MISSING_INPUT

    out = OutputGateNode().execute({"diagnostic_code": ERR_MISSING_INPUT, "result": None, "correlation_id": "c1"})
    assert out["status"] == AgentStatus.SUCCESS.value
    assert out["formatted_output"] == explain_degradation(ERR_MISSING_INPUT)
    assert out["result"] is None  # register not surfaced via the result fallback


def test_output_gate_passes_clean_register():
    result = {"formatted_output": _register(), "status": AgentStatus.SUCCESS.value}
    out = OutputGateNode()._extra_security_gate_output(result)
    assert out["formatted_output"]["entries"][0]["value_selection_rule"] == "latest approved"
