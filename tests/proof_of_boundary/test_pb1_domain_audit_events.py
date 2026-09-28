# PB-1: BaseNode → AuditLogger — domain audit-event coverage.
#
# The framework lifecycle (node_start / node_complete) is proven for every node by
# test_pb_invoke_order.py. THIS module proves the S-4 *domain* event contract: every node under
# src/nodes/ emits its own emit_trace_event() on BOTH the success path AND the fail-closed reject
# path — completing the evidence the docs/03 S-4 map previously carried as [assertion pending]
# (InputHydrateNode, and each node's reject event). It also asserts that a reject delta carries NO
# register fragment and NO inner-working State (fail-closed = owned delta only).
#
# execute() is driven directly (as the per-node unit tests do): it is the layer that owns the domain
# event, and the framework lifecycle/order is PB-6's concern. Imports framework → runs in CI.

import json

import pytest

from framework.schemas.agent_status import AgentStatus
from src.nodes import input_hydrate_node, input_intake_node, manifest_extract_resolve_node
from src.nodes import output_gate_node, provenance_unit_coverage_map_node
from src.nodes import scenario_register_assemble_node, worksheet_value_extract_node

# Inner working State that must never appear in a fail-closed reject delta.
_INNER_WORKING = {"workflow_input", "resolved_rows", "extracted_values", "register_entries", "validated_input"}


def _valid_payload() -> dict:
    # The canonical, contract-valid three inputs (matches the E2E happy path).
    return {
        "municipality": "Shibata City",
        "jed_extract": [{
            "geography": "shibata-city", "time_coverage": "2030-annual", "energy_type": "electricity",
            "unit": "GWh", "value": 1.5, "source_version": "2025.1", "dataset_id": "jed",
        }],
        "version_manifest": {"dataset_id": "jed", "dataset_version": "2025.1", "coverage": {"years": [2030]}},
        "worksheet": [{
            "geography": "shibata-city", "time_coverage": "2030-annual", "energy_type": "electricity",
            "unit": "GWh", "value_selection_rule": "latest approved",
        }],
    }


# (node module, node class, expected reject event) — a minimal/empty state fails each node closed.
# The intake node is not here: an empty request is one the caller can correct, so it completes
# with a notice instead of failing (covered by _DEGRADE_CASES below).
_REJECT_CASES = [
    (input_hydrate_node, input_hydrate_node.InputHydrateNode, "hydrate_rejected"),
    (manifest_extract_resolve_node, manifest_extract_resolve_node.ManifestExtractResolveNode, "extract_resolve_rejected"),
    (worksheet_value_extract_node, worksheet_value_extract_node.WorksheetValueExtractNode, "value_extract_rejected"),
    (provenance_unit_coverage_map_node, provenance_unit_coverage_map_node.ProvenanceUnitCoverageMapNode, "provenance_map_rejected"),
    (scenario_register_assemble_node, scenario_register_assemble_node.ScenarioRegisterAssembleNode, "register_assemble_rejected"),
    (output_gate_node, output_gate_node.OutputGateNode, "output_gate_rejected"),
]


# (node module, node class, expected degrade event) — an empty state is a correctable request.
_DEGRADE_CASES = [
    (input_intake_node, input_intake_node.InputIntakeNode, "inputs_degraded"),
]


def _spy(monkeypatch, module):
    events: list[str] = []
    monkeypatch.setattr(module, "emit_trace_event", lambda name, payload, state: events.append(name))
    return events


@pytest.mark.parametrize("module,node_cls,expected_event", _REJECT_CASES,
                         ids=[c[1].__name__ for c in _REJECT_CASES])
def test_every_node_emits_domain_event_on_reject(monkeypatch, module, node_cls, expected_event):
    events = _spy(monkeypatch, module)
    # An empty state (only a correlation id) drives every node down its fail-closed path.
    out = node_cls().execute({"correlation_id": "pb1"})
    # (1) the domain reject event fired
    assert expected_event in events, f"{node_cls.__name__} did not emit {expected_event}: {events}"
    # (2) the delta is a fail-closed error carrying only a non-sensitive code
    assert out["status"] == AgentStatus.ERROR.value
    # (3) no register fragment and no inner-working State leaks on the reject path
    assert "register" not in out and "register_entries" not in out
    assert not (_INNER_WORKING & set(out))


@pytest.mark.parametrize("module,node_cls,expected_event", _DEGRADE_CASES,
                         ids=[c[1].__name__ for c in _DEGRADE_CASES])
def test_every_node_emits_domain_event_on_degrade(monkeypatch, module, node_cls, expected_event):
    events = _spy(monkeypatch, module)
    out = node_cls().execute({"correlation_id": "pb1"})
    # (1) the domain degrade event fired
    assert expected_event in events, f"{node_cls.__name__} did not emit {expected_event}: {events}"
    # (2) the delta completes the run carrying only a non-sensitive code
    assert out["status"] == AgentStatus.SUCCESS.value
    assert set(out) == {"diagnostic_code", "status"}
    # (3) no register fragment and no inner-working State leaks on the degrade path
    assert not (_INNER_WORKING & set(out))


def test_input_hydrate_emits_domain_event_on_success(monkeypatch):
    # InputHydrateNode has no dedicated unit test; prove its success domain event here so the
    # docs/03 S-4 map no longer needs [assertion pending] for it.
    events = _spy(monkeypatch, input_hydrate_node)
    out = input_hydrate_node.InputHydrateNode().execute(
        {"user_input": json.dumps(_valid_payload()), "correlation_id": "pb1"}
    )
    assert "hydrate" in events
    assert out["status"] == AgentStatus.SUCCESS.value
    assert "workflow_input" in out
