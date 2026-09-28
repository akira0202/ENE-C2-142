# ENE-C2-142 — Cat-2 graph composition / wiring tests (docs/02 Architecture + Data Flow).
#
# Verifies the WIRING deterministically: outer slot registration + fixed backbone, inner node order,
# the GraphNode handoff (extract_input / merge_output) with NO inner-working-State leak, the inner
# get_output allowlist, the error short-circuit predicate, and that both graphs compile. Imports
# framework, so this runs in CI. The compiled-graph invoke() E2E is in test_graph_invoke_e2e.py.

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.graph import MunicipalEnergyScenarioInputEvidenceExtractorGraph  # manifest entry-point
from src.graph.domain_workflow_graph import ScenarioWorkflowGraph
from src.graph.graph import ScenarioExtractWorkflowGraphNode, build_agent
from src.nodes.input_hydrate_node import InputHydrateNode
from src.nodes.input_intake_node import InputIntakeNode
from src.nodes.manifest_extract_resolve_node import ManifestExtractResolveNode
from src.nodes.output_gate_node import OutputGateNode
from src.nodes.provenance_unit_coverage_map_node import ProvenanceUnitCoverageMapNode
from src.nodes.scenario_register_assemble_node import ScenarioRegisterAssembleNode
from src.nodes.worksheet_value_extract_node import WorksheetValueExtractNode
from src.schemas.state import State

# Inner working fields that MUST NOT cross the inner→outer boundary.
_INNER_WORKING = {"workflow_input", "resolved_rows", "extracted_values", "register_entries", "validated_input"}


# ── outer backbone wiring ────────────────────────────────────────────────────
def test_outer_registers_three_slots_plus_backbone():
    graph = MunicipalEnergyScenarioInputEvidenceExtractorGraph(config={})
    graph.register_nodes()
    assert "initialize" in graph._nodes and "finalize" in graph._nodes  # super() first
    assert isinstance(graph._nodes["pre_process"], InputIntakeNode)
    assert isinstance(graph._nodes["main"], ScenarioExtractWorkflowGraphNode)
    assert isinstance(graph._nodes["post_process"], OutputGateNode)


def test_outer_does_not_override_add_edges():
    assert "add_edges" not in MunicipalEnergyScenarioInputEvidenceExtractorGraph.__dict__


def test_name_and_state_schema():
    graph = MunicipalEnergyScenarioInputEvidenceExtractorGraph(config={})
    assert graph.name == "MunicipalEnergyScenarioInputEvidenceExtractor"
    assert graph.state_schema is State


def test_main_graphnode_boundary_and_error_strategy():
    assert ScenarioExtractWorkflowGraphNode.required_trust_level is TrustLevel.VERIFIED_EXTERNAL
    assert ScenarioExtractWorkflowGraphNode.error_strategy == "propagate"


# ── inner workflow wiring ────────────────────────────────────────────────────
def test_inner_registers_five_nodes():
    inner = ScenarioWorkflowGraph(config={})
    inner.register_nodes()
    assert isinstance(inner._nodes["input_hydrate"], InputHydrateNode)
    assert isinstance(inner._nodes["manifest_extract_resolve"], ManifestExtractResolveNode)
    assert isinstance(inner._nodes["worksheet_value_extract"], WorksheetValueExtractNode)
    assert isinstance(inner._nodes["provenance_unit_coverage_map"], ProvenanceUnitCoverageMapNode)
    assert isinstance(inner._nodes["scenario_register_assemble"], ScenarioRegisterAssembleNode)


def test_inner_error_short_circuits_else_continues():
    inner = ScenarioWorkflowGraph(config={})
    assert inner._continue_or_end({"status": AgentStatus.ERROR.value}) == "end"
    assert inner._continue_or_end({"status": AgentStatus.SUCCESS.value}) == "continue"


# ── GraphNode boundary handoff ───────────────────────────────────────────────
def test_extract_input_json_encodes_validated_input():
    node = ScenarioExtractWorkflowGraphNode()
    validated = {"municipality": "Shibata City", "jed_extract": [1]}
    handoff = node.extract_input({"validated_input": validated})
    assert isinstance(handoff, str)
    assert json.loads(handoff) == validated


def test_merge_output_maps_only_register_and_status():
    node = ScenarioExtractWorkflowGraphNode()
    sub_result = {
        "register": {"entries": [], "entry_count": 0, "flagged_count": 0},
        "status": AgentStatus.SUCCESS.value,
        # inner working fields that must NOT be projected outward:
        "workflow_input": {"x": 1}, "resolved_rows": [1], "extracted_values": [1], "register_entries": [1],
    }
    out = node.merge_output({}, sub_result)
    assert set(out) == {"result", "status", "diagnostic_code"}
    assert out["result"] == sub_result["register"]
    assert out["status"] == AgentStatus.SUCCESS.value
    assert out["diagnostic_code"] == ""
    assert not (_INNER_WORKING & set(out))


def test_merge_output_carries_the_inner_degradation_marker():
    node = ScenarioExtractWorkflowGraphNode()
    out = node.merge_output({}, {"register": None, "status": AgentStatus.SUCCESS.value,
                                 "diagnostic_code": "ERR_VERSION_MISMATCH"})
    assert out["diagnostic_code"] == "ERR_VERSION_MISMATCH"
    assert out["result"] is None


def test_merge_output_prefers_the_outer_marker():
    # The outer marker names the specific reason; an inner node can only report its own.
    node = ScenarioExtractWorkflowGraphNode()
    out = node.merge_output({"diagnostic_code": "ERR_MISSING_INPUT"},
                            {"register": None, "status": AgentStatus.SUCCESS.value,
                             "diagnostic_code": "ERR_VERSION_MISMATCH"})
    assert out["diagnostic_code"] == "ERR_MISSING_INPUT"


def test_inner_get_output_is_allowlisted():
    inner = ScenarioWorkflowGraph(config={})
    state = {
        "register": {"entries": [], "entry_count": 0, "flagged_count": 0},
        "status": AgentStatus.SUCCESS.value,
        # inner working fields present in state but must NOT be surfaced:
        "workflow_input": {"x": 1}, "resolved_rows": [1], "extracted_values": [1], "register_entries": [1],
    }
    out = inner.get_output(state)
    assert out["register"] == state["register"]
    assert out["status"] == AgentStatus.SUCCESS.value
    assert not (_INNER_WORKING & set(out))


# ── constructibility + compile ───────────────────────────────────────────────
def test_all_nodes_constructible_argument_free():
    for node_cls in (InputIntakeNode, InputHydrateNode, ManifestExtractResolveNode,
                     WorksheetValueExtractNode, ProvenanceUnitCoverageMapNode,
                     ScenarioRegisterAssembleNode, OutputGateNode, ScenarioExtractWorkflowGraphNode):
        assert node_cls() is not None


def test_both_graphs_compile():
    build_agent().compile()
    ScenarioWorkflowGraph(config={}).compile()
