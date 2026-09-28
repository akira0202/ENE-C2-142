# ENE-C2-142 — Unit tests: ProvenanceUnitCoverageMapNode (inner Step 4).
#
# Covers the S-1 trust declaration, S-4 trace emission, valid mapping to register_entries, and the
# fail-closed reject on structural input problems. Imports framework, so this runs in CI; the
# framework-free mapping logic is covered by test_provenance_mapping.py.

import pytest

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes import provenance_unit_coverage_map_node as node_mod
from src.nodes.provenance_unit_coverage_map_node import ProvenanceUnitCoverageMapNode
from src.services.provenance_mapping import ERR_MAPPING_INPUT, REASON_UNRESOLVABLE_UNIT


def _extracted(status="conformant", unit="GWh", value=1.5):
    return {
        "geography": "shibata-city",
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": unit,
        "value_selection_rule": "latest approved",
        "candidate_count": 1 if status == "conformant" else 0,
        "extraction_status": status,
        "value": value if status == "conformant" else None,
        "provenance": {"dataset_id": "jed", "dataset_version": "2025.1", "source_version": "2025.1"}
        if status == "conformant"
        else {},
    }


def _resolved(unit="GWh"):
    return {
        "geography": "shibata-city",
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": unit,
        "value": 1.5,
        "source_version": "2025.1",
        "dataset_id": "jed",
        "dataset_version": "2025.1",
    }


@pytest.fixture
def trace(monkeypatch):
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda name, payload, state: events.append((name, payload)))
    return events


def _state(extracted, resolved):
    return {"extracted_values": extracted, "resolved_rows": resolved, "correlation_id": "c1"}


def test_s1_required_trust_level_is_anonymous():
    assert ProvenanceUnitCoverageMapNode.required_trust_level == TrustLevel.ANONYMOUS


def test_valid_mapping_emits_register_entries(trace):
    out = ProvenanceUnitCoverageMapNode().execute(_state([_extracted(value=9.0)], [_resolved()]))
    assert out["status"] == AgentStatus.SUCCESS.value
    assert isinstance(out["status"], str)
    e = out["register_entries"][0]
    assert e["value"] == 9.0
    assert e["missing_or_ambiguous"] is None
    assert any(name == "provenance_mapped" for name, _ in trace)


def test_unit_mismatch_flagged_not_converted(trace):
    out = ProvenanceUnitCoverageMapNode().execute(
        _state([_extracted(status="missing", unit="GWh")], [_resolved(unit="TJ")])
    )
    e = out["register_entries"][0]
    assert e["missing_or_ambiguous"] == REASON_UNRESOLVABLE_UNIT
    assert e["value"] is None


def test_missing_inputs_rejected(trace):
    out = ProvenanceUnitCoverageMapNode().execute({"correlation_id": "c1"})  # no extracted_values
    assert out["status"] == AgentStatus.ERROR.value
    assert out["error_log"] == [ERR_MAPPING_INPUT]
    assert "register_entries" not in out
