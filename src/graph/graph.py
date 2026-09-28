"""AgentCore Platform v1.0 — outer graph for ENE-C2-142 (Cat 2, L1-direct AgentBaseGraph).

Backbone is the fixed framework pipeline (add_edges NOT overridden):

    START → initialize → pre_process → main → {route} → post_process → finalize → END

- pre_process  = InputIntakeNode                 (untrusted-input boundary; VERIFIED_EXTERNAL)
- main         = ScenarioExtractWorkflowGraphNode (wraps the inner ScenarioWorkflowGraph)
- post_process = OutputGateNode                  (terminal S-3 gate)

The inner domain workflow is hidden inside `main` via a GraphNode. On inner success the framework
route() sends `main → post_process` (the terminal S-3 gate publishes formatted_output); on inner
error the GraphNode (error_strategy="propagate") raises SubgraphError, `main` returns status:error,
route() sends it straight to `finalize` (post_process skipped) and the caller output is empty — no
partial register. `merge_output()` maps ONLY the terminal register/status outward; inner working
State never crosses the boundary.
"""

import json
from typing import Any, ClassVar

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.graph.domain_workflow_graph import ScenarioWorkflowGraph
from src.nodes.input_intake_node import InputIntakeNode
from src.nodes.output_gate_node import OutputGateNode
from src.schemas.state import State
from src.services.progress import emit_progress


class ScenarioExtractWorkflowGraphNode(GraphNode):
    """`main` slot — runs the inner ScenarioWorkflowGraph as an in-process subgraph."""

    # Outer-boundary node (docs/02 §Trust boundary): a verified external caller.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL
    # Inner error → SubgraphError → outer finalize (no partial output). A request the caller can
    # correct is not an error: the inner graph completes carrying diagnostic_code, which is mapped
    # outward by merge_output (an inner error would be re-raised before merge_output ever runs).
    error_strategy: ClassVar[str] = "propagate"

    def __init__(self, node_config: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._config = node_config or {}

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # A request already answered at pre_process carries no validated_input, so there is nothing
        # to hand over: running the inner workflow would only re-reject an empty payload.
        code = state.get("diagnostic_code")
        if code:
            emit_trace_event(
                "scenario_workflow_skipped",
                {"correlation_id": state.get("correlation_id"), "diagnostic_code": code},
                state,
            )
            return {"status": AgentStatus.SUCCESS.value}
        merged: dict[str, Any] = super().execute(state)
        return merged

    def get_subgraph(self) -> ScenarioWorkflowGraph:
        return ScenarioWorkflowGraph(config=self._config)

    def extract_input(self, state: dict[str, Any]) -> str:
        # Hand the canonical validated_input to the inner graph as a JSON string (deterministic:
        # sorted keys, ascii). The inner InputHydrateNode parses + re-validates it.
        emit_progress("Extracting the scenario inputs and their evidence...")
        return json.dumps(state.get("validated_input", {}), ensure_ascii=True, sort_keys=True)

    def merge_output(self, state: dict[str, Any], sub_result: dict[str, Any]) -> dict[str, Any]:
        # Explicit boundary mapping ONLY — the terminal register (result) + status. No inner working
        # field (workflow_input / resolved_rows / extracted_values / register_entries) is passed
        # through.
        # The degradation marker is mapped like every other field: post_process reads it to report
        # the reason instead of a register. The outer marker wins — it names the specific reason,
        # while an inner node can only report its own.
        return {
            "result": sub_result.get("register"),
            "status": sub_result.get("status"),
            "diagnostic_code": state.get("diagnostic_code") or sub_result.get("diagnostic_code") or "",
        }


class MunicipalEnergyScenarioInputEvidenceExtractorGraph(AgentBaseGraph):
    """Outer Cat-2 backbone. Domain complexity lives in the `main` GraphNode; add_edges() is not
    overridden (the framework wires the fixed backbone)."""

    @property
    def name(self) -> str:
        return "MunicipalEnergyScenarioInputEvidenceExtractor"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize (required first)
        self._nodes["pre_process"] = InputIntakeNode()
        self._nodes["main"] = ScenarioExtractWorkflowGraphNode(node_config=self.config)
        self._nodes["post_process"] = OutputGateNode()

    # add_edges() is NOT overridden — the framework owns the backbone wiring.


def build_agent(config: dict[str, Any] | None = None) -> MunicipalEnergyScenarioInputEvidenceExtractorGraph:
    """Construct the agent graph. v1 needs no runtime config (deterministic, LLM-free core path)."""
    return MunicipalEnergyScenarioInputEvidenceExtractorGraph(config=config or {})
