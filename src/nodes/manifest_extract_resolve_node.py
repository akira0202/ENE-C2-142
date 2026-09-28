"""AgentCore Platform v1.0 — ManifestExtractResolveNode for ENE-C2-142 (inner Step 2).

Node contract:
 - Extend FunctionNode; implement execute(state) -> dict.
 - Return ONLY the fields this node changes (never {**state}).
 - Return AgentStatus.<X>.value strings — never the bare Enum object.
 - Never import from mediator/, api/, src/graph/, or other agents.

Responsibility (docs/02 — inner manifest_extract_resolve / Step 2):
 - Sole owner of manifest↔extract resolution. Reads the hydrated workflow_input, requires exact
   dataset_id/dataset_version consistency (every extract row's source_version equals the manifest's
   approved dataset_version), fails closed on any missing/unknown/superseded/schema-mismatched
   version with no fallback, and writes resolved_rows stamped with the dataset identity and the
   available provenance (immutable identifier/URL, checksum when supplied).
 - It is an inner-graph node (S-1 enforced once at the outer boundary) — required_trust_level is
   ANONYMOUS. It performs NO input presence/format validation (the intake node) and NO value
   extraction (the next node).
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.degradation import DEGRADATION_CODES
from src.services.manifest_resolution import ERR_MANIFEST_SCHEMA, ResolutionError, resolve
from src.services.failure_message import explain
from src.services.progress import emit_progress


def _has_sentence(reason: str) -> bool:
    """True when `reason` resolves to a sentence of its own rather than the general fallback."""
    return explain(reason) != explain("__no_such_code__")


class ManifestExtractResolveNode(FunctionNode):
    """Inner node — resolve the approved extract against the version manifest, fail closed on any
    version mismatch, and stamp provenance onto the resolved rows."""

    # S-1: inner-graph node; the outer boundary already enforced VERIFIED_EXTERNAL.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        workflow_input = state.get("workflow_input")
        if workflow_input is None:
            return self._reject(state, ERR_MANIFEST_SCHEMA, "missing_workflow_input")

        try:
            resolved_rows = resolve(workflow_input)
        except ResolutionError as exc:
            if exc.code in DEGRADATION_CODES:
                # The caller's rows disagree with the manifest they were sent with: correctable.
                emit_trace_event(
                    "extract_resolve_degraded",
                    {"correlation_id": state.get("correlation_id"), "code": exc.code},
                    state,
                )
                return {"diagnostic_code": exc.code, "status": AgentStatus.SUCCESS.value}
            return self._reject(state, exc.code, "resolution_failed")

        emit_trace_event(
            "extract_resolved",
            {
                "correlation_id": state.get("correlation_id"),
                "resolved_row_count": len(resolved_rows),
                "dataset_version": resolved_rows[0]["dataset_version"] if resolved_rows else None,
            },
            state,
        )
        return {"resolved_rows": resolved_rows, "status": AgentStatus.SUCCESS.value}

    # --- fail-closed helper: owned delta only; code in error_log, slug in the trace event ---
    def _reject(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # `reason` names the specific cause (malformed_json, too_deep, ...) while `code` is the
        # coarse contract bucket the run fails under. Explaining the code alone collapses every
        # rejection to one sentence, so prefer the reason and fall back to the code only when it
        # has no sentence of its own.
        emit_progress(explain(reason) if _has_sentence(reason) else explain(code))
        emit_trace_event(
            "extract_resolve_rejected",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        return {"status": AgentStatus.ERROR.value, "error_log": [code]}
