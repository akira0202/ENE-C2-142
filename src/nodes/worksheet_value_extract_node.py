"""AgentCore Platform v1.0 — WorksheetValueExtractNode for ENE-C2-142 (inner Step 3).

Node contract:
 - Extend FunctionNode; implement execute(state) -> dict.
 - Return ONLY the fields this node changes (never {**state}).
 - Return AgentStatus.<X>.value strings — never the bare Enum object.
 - Never import from mediator/, api/, src/graph/, or other agents.

Responsibility (docs/02 — inner worksheet_value_extract / Step 3):
 - Reads the resolved rows and the worksheet directives from state and extracts the directed values.
   The declared value_selection_rule is recorded verbatim and never applied — the node does not
   choose between candidates, interpolate, infer, or silently transform values. Each directive yields
   a structured entry flagged conformant / missing / ambiguous; missing and ambiguous carry no value.
 - Inner-graph node — required_trust_level is ANONYMOUS (S-1 enforced at the outer boundary). It does
   no version resolution (the previous node) and no provenance/unit-coverage mapping or register
   assembly (later nodes).
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.value_extraction import ExtractionError, extract_values
from src.services.failure_message import explain
from src.services.progress import emit_progress


def _has_sentence(reason: str) -> bool:
    """True when `reason` resolves to a sentence of its own rather than the general fallback."""
    return explain(reason) != explain("__no_such_code__")


class WorksheetValueExtractNode(FunctionNode):
    """Inner node — extract worksheet-directed values from the resolved rows, recording (never
    applying) the value-selection rule and flagging missing / ambiguous references."""

    # S-1: inner-graph node; the outer boundary already enforced VERIFIED_EXTERNAL.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        resolved_rows = state.get("resolved_rows")
        workflow_input = state.get("workflow_input")
        worksheet = workflow_input.get("worksheet") if isinstance(workflow_input, dict) else None

        try:
            extracted = extract_values(resolved_rows, worksheet)
        except ExtractionError as exc:
            return self._reject(state, exc.code, "extraction_failed")

        flagged = sum(1 for e in extracted if e["extraction_status"] != "conformant")
        emit_trace_event(
            "values_extracted",
            {
                "correlation_id": state.get("correlation_id"),
                "extracted_count": len(extracted),
                "flagged_count": flagged,
            },
            state,
        )
        return {"extracted_values": extracted, "status": AgentStatus.SUCCESS.value}

    # --- fail-closed helper: owned delta only; code in error_log, slug in the trace event ---
    def _reject(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # `reason` names the specific cause (malformed_json, too_deep, ...) while `code` is the
        # coarse contract bucket the run fails under. Explaining the code alone collapses every
        # rejection to one sentence, so prefer the reason and fall back to the code only when it
        # has no sentence of its own.
        emit_progress(explain(reason) if _has_sentence(reason) else explain(code))
        emit_trace_event(
            "value_extract_rejected",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        return {"status": AgentStatus.ERROR.value, "error_log": [code]}
