# ENE-C2-142 — Unit tests: ScenarioRegisterAssembleNode (inner Step 5).
#
# Covers the S-1 trust declaration, S-4 trace emission, valid assembly to register, and the
# fail-closed reject on structural input. Imports framework, so this runs in CI; the framework-free
# assembly logic is covered by test_register_assembly.py.

import pytest

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes import scenario_register_assemble_node as node_mod
from src.nodes.scenario_register_assemble_node import ScenarioRegisterAssembleNode
from src.services.register_assembly import ERR_ASSEMBLY_INPUT


def _entry(reason=None, value=1.5):
    ok = reason is None
    return {
        "geography": "shibata-city",
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": "GWh",
        "source_version": "2025.1" if ok else None,
        "value_selection_rule": "latest approved",
        "missing_or_ambiguous": reason,
        "value": value if ok else None,
        "source_id": "jed" if ok else None,
        "provenance": {"dataset_id": "jed", "dataset_version": "2025.1", "source_version": "2025.1"} if ok else {},
    }


@pytest.fixture
def trace(monkeypatch):
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda name, payload, state: events.append((name, payload)))
    return events


def test_s1_required_trust_level_is_anonymous():
    assert ScenarioRegisterAssembleNode.required_trust_level == TrustLevel.ANONYMOUS


def test_valid_assembly_emits_register(trace):
    out = ScenarioRegisterAssembleNode().execute({"register_entries": [_entry(value=9.0)], "correlation_id": "c1"})
    assert out["status"] == AgentStatus.SUCCESS.value
    assert isinstance(out["status"], str)
    assert out["register"]["entry_count"] == 1
    assert out["register"]["entries"][0]["value"] == 9.0
    assert any(name == "register_assembled" for name, _ in trace)


def test_missing_input_rejected(trace):
    out = ScenarioRegisterAssembleNode().execute({"correlation_id": "c1"})  # no register_entries
    assert out["status"] == AgentStatus.ERROR.value
    assert out["error_log"] == [ERR_ASSEMBLY_INPUT]
    assert "register" not in out
