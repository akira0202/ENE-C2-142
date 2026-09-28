"""AgentCore Platform v1.0 — inner scenario-input workflow graph for ENE-C2-142 (Cat 2).

The inner `BaseGraph` wrapped by `ScenarioExtractWorkflowGraphNode` (the outer `main` slot). It runs
the linear domain pipeline over the canonical validated_input handed in as a JSON string:

    START → input_hydrate → manifest_extract_resolve → worksheet_value_extract
          → provenance_unit_coverage_map → scenario_register_assemble → END

Any inner node that returns `status: error` short-circuits to END (via a conditional edge) so the
inner graph produces NO partial output; the outer `GraphNode(error_strategy="propagate")` then
raises SubgraphError from that error status and the outer run ends fail-closed (post_process is
skipped, caller output is empty). `get_output()` surfaces ONLY the terminal `register` plus framework
metadata — never inner working State (workflow_input / resolved_rows / extracted_values /
register_entries).
"""

from typing import Any

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_status import AgentStatus

from src.nodes.input_hydrate_node import InputHydrateNode
from src.nodes.manifest_extract_resolve_node import ManifestExtractResolveNode
from src.nodes.provenance_unit_coverage_map_node import ProvenanceUnitCoverageMapNode
from src.nodes.scenario_register_assemble_node import ScenarioRegisterAssembleNode
from src.nodes.worksheet_value_extract_node import WorksheetValueExtractNode
from src.schemas.state import ScenarioWorkflowState


class ScenarioWorkflowGraph(BaseGraph):
    """Inner Cat-2 domain workflow (linear, fail-closed short-circuit on any node error)."""

    @property
    def name(self) -> str:
        return "scenario_input_workflow"

    @property
    def state_schema(self) -> type:
        return ScenarioWorkflowState

    def _validate_config(self) -> None:
        # No mandatory config: the v1 core path is deterministic and LLM-free.
        return None

    def register_nodes(self) -> None:
        # No super() call — initialize/finalize are the outer backbone's concern, not the inner graph.
        self._nodes["input_hydrate"] = InputHydrateNode()
        self._nodes["manifest_extract_resolve"] = ManifestExtractResolveNode()
        self._nodes["worksheet_value_extract"] = WorksheetValueExtractNode()
        self._nodes["provenance_unit_coverage_map"] = ProvenanceUnitCoverageMapNode()
        self._nodes["scenario_register_assemble"] = ScenarioRegisterAssembleNode()

    def add_edges(self) -> None:
        # Each hop is conditional: a node returning status:error routes to END (no partial output),
        # otherwise it advances to the next inner node.
        self._sg.add_edge(START, "input_hydrate")
        self._sg.add_conditional_edges(
            "input_hydrate",
            self._continue_or_end,
            {"continue": "manifest_extract_resolve", "end": END},
        )
        self._sg.add_conditional_edges(
            "manifest_extract_resolve",
            self._continue_or_end,
            {"continue": "worksheet_value_extract", "end": END},
        )
        self._sg.add_conditional_edges(
            "worksheet_value_extract",
            self._continue_or_end,
            {"continue": "provenance_unit_coverage_map", "end": END},
        )
        self._sg.add_conditional_edges(
            "provenance_unit_coverage_map",
            self._continue_or_end,
            {"continue": "scenario_register_assemble", "end": END},
        )
        self._sg.add_edge("scenario_register_assemble", END)

    def _continue_or_end(self, state: dict[str, Any]) -> str:
        """END on any node error, and on a run already answered with a diagnostic_code; otherwise
        advance to the next inner node. A degraded run ends as SUCCESS, so keying only on the
        status would let the remaining nodes run on a request that was already answered.

        The annotation stays ``dict[str, Any]`` so the graph engine hands this function the whole
        state: a TypedDict annotation would build the state from that type's fields only, and a
        marker declared elsewhere would not arrive."""
        if state.get("diagnostic_code"):
            return "end"
        return "end" if state.get("status") == AgentStatus.ERROR.value else "continue"

    def route(self, state: dict[str, Any]) -> str:
        # Required by the BaseGraph ABC; the per-hop edges use _continue_or_end().
        return self._continue_or_end(state)

    def get_output(self, state: dict[str, Any]) -> dict[str, Any]:
        # Minimal, allowlisted surface: the terminal register + framework metadata only. No inner
        # working State (workflow_input / resolved_rows / extracted_values / register_entries) is
        # projected outward.
        return {
            "register": state.get("register"),
            "status": state.get("status"),
            # The marker is projected explicitly: on a run the caller can correct, the inner graph
            # completes (rather than erroring) precisely so this can cross the boundary.
            "diagnostic_code": state.get("diagnostic_code"),
            "error_log": state.get("error_log", []),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
