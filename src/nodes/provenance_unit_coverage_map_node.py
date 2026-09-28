"""AgentCore Platform v1.0 — ProvenanceUnitCoverageMapNode for ENE-C2-142 (inner Step 4).

Node contract:
 - Extend FunctionNode; implement execute(state) -> dict.
 - Return ONLY the fields this node changes (never {**state}).
 - Return AgentStatus.<X>.value strings — never the bare Enum object.
 - Never import from mediator/, api/, src/graph/, or other agents.

Responsibility (docs/02 — inner provenance_unit_coverage_map / Step 4):
 - Maps each extracted value to its provenance (source version, source identifier) and resolves its
   unit/time-coverage status, attaching design-defined missing/ambiguous/unit-mismatch/coverage-gap
   reason codes. Unknown units or absent conversion rules are flagged, never converted.
 - Inner-graph node — required_trust_level is ANONYMOUS. It does NOT serialize the final register or
   make data-quality/comparability/scenario decisions (the assembly node's job); it emits the mapped
   register_entries only.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.provenance_mapping import MappingError, map_provenance_coverage
from src.services.failure_message import explain
from src.services.progress import emit_progress


def _has_sentence(reason: str) -> bool:
    """True when `reason` resolves to a sentence of its own rather than the general fallback."""
    return explain(reason) != explain("__no_such_code__")


class ProvenanceUnitCoverageMapNode(FunctionNode):
    """Inner node — map provenance and unit/time-coverage onto the extracted values, attaching the
    design-defined status/reason codes and never converting units."""

    # S-1: inner-graph node; the outer boundary already enforced VERIFIED_EXTERNAL.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        extracted_values = state.get("extracted_values")
        resolved_rows = state.get("resolved_rows")

        try:
            register_entries = map_provenance_coverage(extracted_values, resolved_rows)
        except MappingError as exc:
            return self._reject(state, exc.code, "mapping_failed")

        flagged = sum(1 for e in register_entries if e["missing_or_ambiguous"] is not None)
        emit_trace_event(
            "provenance_mapped",
            {
                "correlation_id": state.get("correlation_id"),
                "entry_count": len(register_entries),
                "flagged_count": flagged,
            },
            state,
        )
        return {"register_entries": register_entries, "status": AgentStatus.SUCCESS.value}

    # --- fail-closed helper: owned delta only; code in error_log, slug in the trace event ---
    def _reject(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # `reason` names the specific cause (malformed_json, too_deep, ...) while `code` is the
        # coarse contract bucket the run fails under. Explaining the code alone collapses every
        # rejection to one sentence, so prefer the reason and fall back to the code only when it
        # has no sentence of its own.
        emit_progress(explain(reason) if _has_sentence(reason) else explain(code))
        emit_trace_event(
            "provenance_map_rejected",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        return {"status": AgentStatus.ERROR.value, "error_log": [code]}
