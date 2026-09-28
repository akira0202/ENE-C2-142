# ENE-C2-142 — Unit tests: ManifestExtractResolveNode (inner Step 2).
#
# Covers the S-1 trust declaration, S-4 trace emission, valid resolution to resolved_rows, and the
# fail-closed rejects (owned delta only, non-sensitive code, no partial resolution). Imports
# framework, so this runs in CI; the framework-free resolution logic is covered by
# test_manifest_resolution.py.

import pytest

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes import manifest_extract_resolve_node as node_mod
from src.nodes.manifest_extract_resolve_node import ManifestExtractResolveNode
from src.services.manifest_resolution import ERR_MANIFEST_SCHEMA, ERR_VERSION_MISMATCH


def _workflow_input(source_version="2025.1"):
    return {
        "municipality": "Shibata City",
        "jed_extract": [
            {
                "geography": "shibata-city",
                "time_coverage": "2030-annual",
                "energy_type": "electricity",
                "unit": "GWh",
                "value": 1.5,
                "source_version": source_version,
                "dataset_id": "jed",
            }
        ],
        "version_manifest": {"dataset_id": "jed", "dataset_version": "2025.1", "coverage": {"years": [2030]}},
        "worksheet": [],
    }


@pytest.fixture
def trace(monkeypatch):
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda name, payload, state: events.append((name, payload)))
    return events


def _run(workflow_input):
    state = {"workflow_input": workflow_input, "correlation_id": "c1"}
    return ManifestExtractResolveNode().execute(state)


def test_s1_required_trust_level_is_anonymous():
    assert ManifestExtractResolveNode.required_trust_level == TrustLevel.ANONYMOUS


def test_valid_resolution_emits_resolved_rows(trace):
    out = _run(_workflow_input())
    assert out["status"] == AgentStatus.SUCCESS.value
    assert isinstance(out["status"], str)
    assert len(out["resolved_rows"]) == 1
    assert out["resolved_rows"][0]["dataset_version"] == "2025.1"
    assert any(name == "extract_resolved" for name, _ in trace)


def _assert_rejected(out, code):
    # Rows that disagree with the manifest they were sent with are the caller's to correct: the
    # run completes carrying the code, resolves nothing, and the later inner nodes are skipped.
    assert out == {"diagnostic_code": code, "status": AgentStatus.SUCCESS.value}


def _assert_failed_closed(out, code):
    assert out["status"] == AgentStatus.ERROR.value
    assert out["error_log"] == [code]
    assert "resolved_rows" not in out  # owned delta only, no partial resolution


def test_missing_workflow_input_fails_closed(trace):
    # The previous node is contracted to set workflow_input: its absence is a defect in this
    # agent, not a request the caller can correct, so it stays fail-closed.
    out = ManifestExtractResolveNode().execute({"correlation_id": "c1"})
    _assert_failed_closed(out, ERR_MANIFEST_SCHEMA)


def test_version_mismatch_degrades(trace):
    out = _run(_workflow_input(source_version="2024.3"))
    _assert_rejected(out, ERR_VERSION_MISMATCH)
