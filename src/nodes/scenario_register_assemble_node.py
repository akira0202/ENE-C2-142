"""AgentCore Platform v1.0 — ScenarioRegisterAssembleNode for ENE-C2-142 (inner Step 5).

Node contract:
 - Extend FunctionNode; implement execute(state) -> dict.
 - Return ONLY the fields this node changes (never {**state}).
 - Return AgentStatus.<X>.value strings — never the bare Enum object.
 - Never import from mediator/, api/, src/graph/, or other agents.

Responsibility (docs/02 — inner scenario_register_assemble / Step 5 assembly):
 - Serializes the mapped register entries into the human-review scenario-input register (seven
   mandatory fields + value + allowed provenance). The missing/ambiguous status is consumed verbatim
   from the mapping step and never re-evaluated. Fails closed with no partial register.
 - Inner-graph node — required_trust_level is ANONYMOUS. Output safety (S-3) and name masking are
   the outer output gate's job.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.register_assembly import AssemblyError, assemble_register
from src.services.failure_message import explain
from src.services.progress import emit_progress


def _has_sentence(reason: str) -> bool:
    """True when `reason` resolves to a sentence of its own rather than the general fallback."""
    return explain(reason) != explain("__no_such_code__")


class ScenarioRegisterAssembleNode(FunctionNode):
    """Inner node — assemble the seven-field scenario-input register from the mapped entries,
    consuming the missing/ambiguous status without re-evaluation and never returning a partial
    register."""

    # S-1: inner-graph node; the outer boundary already enforced VERIFIED_EXTERNAL.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        register_entries = state.get("register_entries")

        try:
            register = assemble_register(register_entries)
        except AssemblyError as exc:
            return self._reject(state, exc.code, "assembly_failed")

        emit_trace_event(
            "register_assembled",
            {
                "correlation_id": state.get("correlation_id"),
                "entry_count": register["entry_count"],
                "flagged_count": register["flagged_count"],
            },
            state,
        )
        return {"register": register, "status": AgentStatus.SUCCESS.value}

    # --- fail-closed helper: owned delta only; code in error_log, slug in the trace event ---
    def _reject(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # `reason` names the specific cause (malformed_json, too_deep, ...) while `code` is the
        # coarse contract bucket the run fails under. Explaining the code alone collapses every
        # rejection to one sentence, so prefer the reason and fall back to the code only when it
        # has no sentence of its own.
        emit_progress(explain(reason) if _has_sentence(reason) else explain(code))
        emit_trace_event(
            "register_assemble_rejected",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        return {"status": AgentStatus.ERROR.value, "error_log": [code]}
