# ENE-C2-142 — Unit tests: InputIntakeNode (outer pre_process).
#
# Covers the S-1 trust declaration, the S-2 structural gate, S-4 trace emission, the valid
# pass-through to validated_input, and the fail-closed rejects (owned delta only, non-sensitive
# code, no raw payload echoed). Graph wiring is a later issue. Imports framework, so this runs
# in CI (run-tests); the framework-free contract logic is covered by test_input_schema.py.

import json

import pytest

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes import input_intake_node as node_mod
from src.nodes.input_intake_node import InputIntakeNode
from src.services.input_schema import ERR_MISSING_INPUT, ERR_MUNICIPALITY, ERR_SCHEMA


def _valid_payload():
    return {
        "municipality": "Shibata City",
        "jed_extract": [
            {
                "geography": "shibata-city",
                "time_coverage": "2030-annual",
                "energy_type": "electricity",
                "unit": "GWh",
                "value": 1.5,
                "source_version": "2025.1",
                "dataset_id": "jed",
            }
        ],
        "version_manifest": {"dataset_id": "jed", "dataset_version": "2025.1", "coverage": {"years": [2030]}},
        "worksheet": [
            {
                "geography": "shibata-city",
                "time_coverage": "2030-annual",
                "energy_type": "electricity",
                "unit": "GWh",
                "value_selection_rule": "latest approved",
            }
        ],
    }


@pytest.fixture
def trace(monkeypatch):
    """Capture emitted trace events (S-4)."""
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda name, payload, state: events.append((name, payload)))
    return events


def _run(payload_or_raw):
    raw = payload_or_raw if isinstance(payload_or_raw, str) else json.dumps(payload_or_raw)
    return InputIntakeNode().execute({"user_input": raw, "correlation_id": "c1"})


# --- S-1: trust declaration ---------------------------------------------------------------
def test_s1_required_trust_level_is_verified_external():
    assert InputIntakeNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL


# --- valid pass-through -------------------------------------------------------------------
def test_valid_input_emits_validated_input(trace):
    out = _run(_valid_payload())
    assert out["status"] == AgentStatus.SUCCESS.value
    assert isinstance(out["status"], str)
    assert out["validated_input"]["municipality"] == "Shibata City"
    assert len(out["validated_input"]["jed_extract"]) == 1
    # S-4: a domain trace event is emitted on success.
    assert any(name == "inputs_validated" for name, _ in trace)


# --- fail-closed rejects (owned delta only, no raw echo) ----------------------------------
def _assert_rejected(out, code):
    # A request the caller can correct: the run completes carrying the code, hands on nothing
    # validated, and logs no error — post_process turns the code into the notice.
    assert out == {"diagnostic_code": code, "status": AgentStatus.SUCCESS.value}         # owned delta only, no partial output


def test_malformed_json_rejected(trace):
    out = _run("{not valid json")
    _assert_rejected(out, ERR_SCHEMA)
    assert any(name == "inputs_degraded" for name, _ in trace)


def test_empty_input_rejected(trace):
    out = InputIntakeNode().execute({"user_input": "   ", "correlation_id": "c1"})
    _assert_rejected(out, ERR_SCHEMA)


def test_missing_input_rejected(trace):
    p = _valid_payload()
    del p["worksheet"]
    _assert_rejected(_run(p), ERR_MISSING_INPUT)


def test_municipality_rejected(trace):
    p = _valid_payload()
    p["municipality"] = ""
    _assert_rejected(_run(p), ERR_MUNICIPALITY)


def test_reject_does_not_echo_payload(trace):
    # A distinctive payload value must never appear in the returned delta (no raw-data echo).
    marker = "ZZZ_NO_ECHO_MARKER_ZZZ"
    p = _valid_payload()
    p["jed_extract"][0]["raw_blob"] = marker  # unknown key -> ERR_SCHEMA
    out = _run(p)
    _assert_rejected(out, ERR_SCHEMA)
    assert marker not in json.dumps(out)


# --- S-2: structural gate -----------------------------------------------------------------
def test_s2_gate_rejects_nul_byte():
    out = InputIntakeNode()._extra_security_gate_input({"user_input": "payload\x00smuggled", "correlation_id": "c1"})
    assert out["status"] == AgentStatus.ERROR.value
    assert out["error_log"] == [ERR_SCHEMA]


def test_s2_gate_passes_clean_payload():
    state = {"user_input": json.dumps(_valid_payload()), "correlation_id": "c1"}
    out = InputIntakeNode()._extra_security_gate_input(state)
    assert out is state  # clean payload passes through untouched


def test_s2_gate_passes_through_missing_input():
    # Missing user_input must pass the S-2 gate (execute() surfaces it) so the framework invoke
    # order is preserved: gate-level rejection would short-circuit execute()/S-3 (PB-6).
    state = {"correlation_id": "c1"}  # no user_input
    out = InputIntakeNode()._extra_security_gate_input(state)
    assert out is state
