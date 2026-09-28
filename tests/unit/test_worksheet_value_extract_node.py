# ENE-C2-142 — Unit tests: WorksheetValueExtractNode (inner Step 3).
#
# Covers the S-1 trust declaration, S-4 trace emission, valid extraction to extracted_values, the
# no-choice ambiguity flag, and the fail-closed reject on structural input problems. Imports
# framework, so this runs in CI; the framework-free extraction logic is in test_value_extraction.py.

import pytest

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes import worksheet_value_extract_node as node_mod
from src.nodes.worksheet_value_extract_node import WorksheetValueExtractNode
from src.services.value_extraction import ERR_EXTRACT_INPUT


def _resolved(unit="GWh", value=1.5):
    return {
        "geography": "shibata-city",
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": unit,
        "value": value,
        "source_version": "2025.1",
        "dataset_id": "jed",
        "dataset_version": "2025.1",
    }


def _directive(unit="GWh", rule="latest approved"):
    return {
        "geography": "shibata-city",
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": unit,
        "value_selection_rule": rule,
    }


def _state(resolved, worksheet):
    return {
        "resolved_rows": resolved,
        "workflow_input": {"worksheet": worksheet},
        "correlation_id": "c1",
    }


@pytest.fixture
def trace(monkeypatch):
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda name, payload, state: events.append((name, payload)))
    return events


def test_s1_required_trust_level_is_anonymous():
    assert WorksheetValueExtractNode.required_trust_level == TrustLevel.ANONYMOUS


def test_valid_extraction_emits_extracted_values(trace):
    out = WorksheetValueExtractNode().execute(_state([_resolved(value=9.0)], [_directive()]))
    assert out["status"] == AgentStatus.SUCCESS.value
    assert isinstance(out["status"], str)
    assert out["extracted_values"][0]["extraction_status"] == "conformant"
    assert out["extracted_values"][0]["value"] == 9.0
    assert any(name == "values_extracted" for name, _ in trace)


def test_ambiguous_reference_chooses_nothing(trace):
    out = WorksheetValueExtractNode().execute(_state([_resolved(value=1.0), _resolved(value=2.0)], [_directive()]))
    assert out["status"] == AgentStatus.SUCCESS.value
    e = out["extracted_values"][0]
    assert e["extraction_status"] == "ambiguous"
    assert e["value"] is None


def test_missing_inputs_rejected(trace):
    out = WorksheetValueExtractNode().execute({"correlation_id": "c1"})  # no resolved_rows / workflow_input
    assert out["status"] == AgentStatus.ERROR.value
    assert out["error_log"] == [ERR_EXTRACT_INPUT]
    assert "extracted_values" not in out
