"""AgentCore Platform v1.0 — InputIntakeNode for ENE-C2-142 (outer pre_process).

Node contract:
 - Extend FunctionNode; implement execute(state) -> dict.
 - Return ONLY the fields this node changes (never {**state} — error_log / node_history are
   operator.add reducer channels, so spreading state double-appends the audit trail).
 - Return AgentStatus.<X>.value strings — never the bare Enum object.
 - Never import from mediator/, api/, src/graph/, or other agents.

Responsibility (docs/02 — outer pre_process / InputIntakeNode row):
 - Receives the framework-inherited user_input: str (a JSON string of the three supplied inputs),
   parses it, and enforces the v1 three-input contract (extract / version manifest / worksheet),
   one municipality per invocation, structural/schema validity, and safe canonical normalization,
   writing the JSON/msgpack-safe validated_input. It builds NO inner domain value and does NOT touch
   result — those belong to the inner workflow graph. The main GraphNode.extract_input() JSON-encodes
   validated_input into the inner user_input; the inner input_hydrate restores it.
 - It does NOT decide dataset/version or manifest-to-extract cross-reference consistency — that
   deterministic resolution belongs exclusively to the resolution node (Step 2).
 - S-2 lives in _extra_security_gate_input(): STRUCTURAL screen of the raw string only (non-str /
   NUL / control-character / oversized). The framework @final _security_gate_input() (baseline PII
   scan) is NOT overridden and still runs. No lexical/semantic prompt-injection heuristic — v1 has
   no LLM boundary; credential egress is caught at the terminal output gate (later issue).
 - execute() validates via src/services/input_schema.py and fails closed with a non-sensitive error
   CODE (never payload content). No retrieval / refresh / inference / gap-filling; approval
   authenticity is trusted at the VERIFIED_EXTERNAL boundary, not re-verified.
"""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.degradation import DEGRADATION_CODES
from src.services.input_schema import (
    ERR_SCHEMA,
    InputContractError,
    structural_screen,
    validate_and_normalize,
)
from src.services.progress import emit_progress
from src.services.failure_message import explain


def _has_sentence(reason: str) -> bool:
    """True when `reason` resolves to a sentence of its own rather than the general fallback."""
    return explain(reason) != explain("__no_such_code__")


class InputIntakeNode(FunctionNode):
    """Outer pre_process node — untrusted-input boundary: parse + validate the three supplied
    inputs, fail closed on malformed / missing / unsafe input without echoing the payload."""

    # S-1 (docs/02 §Trust boundary): the outer boundary requires a verified external caller.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    # --- S-2 structural gate (runs before execute(); never raises, returns a dict) --------
    def _extra_security_gate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get("user_input")
        if raw is None:
            return state  # missing input is surfaced by execute() (preserves the invoke order)
        code = structural_screen(raw)
        if code is not None:
            return self._reject(state, code, "s2_structural")
        return state

    # --- business validation ---------------------------------------------------------------
    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emit_progress("Checking the request...")
        raw = state.get("user_input")
        if not isinstance(raw, str) or not raw.strip():
            return self._degrade(state, ERR_SCHEMA, "empty_or_missing")

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return self._degrade(state, ERR_SCHEMA, "malformed_json")
        except RecursionError:
            return self._degrade(state, ERR_SCHEMA, "too_deep")

        try:
            validated_input = validate_and_normalize(payload)
        except InputContractError as exc:
            return self._degrade(state, exc.code, "contract_violation")

        emit_trace_event(
            "inputs_validated",
            {
                "correlation_id": state.get("correlation_id"),
                "municipality_present": bool(validated_input["municipality"]),
                "extract_row_count": len(validated_input["jed_extract"]),
                "worksheet_row_count": len(validated_input["worksheet"]),
            },
            state,
        )
        return {"validated_input": validated_input, "status": AgentStatus.SUCCESS.value}

    # --- degraded completion: the caller can correct the request -----------------------------
    def _degrade(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        """Complete the run carrying the reason instead of failing: the caller can correct this
        request. Only the allow-listed code is recorded — never payload content. A code this agent
        has no notice for is a defect, not a caller correction, so it stays fail-closed."""
        if code not in DEGRADATION_CODES:
            return self._reject(state, code, reason)
        emit_trace_event(
            "inputs_degraded",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        return {"diagnostic_code": code, "status": AgentStatus.SUCCESS.value}

    # --- fail-closed helper: owned delta only; code in error_log, slug in the trace event ---
    def _reject(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # Payload is never echoed — only the non-sensitive code / reason slug / correlation_id.
        # `reason` names the specific cause (malformed_json, too_deep, ...) while `code` is the
        # coarse contract bucket the run fails under. Explaining the code alone collapses every
        # rejection to one sentence, so prefer the reason and fall back to the code only when it
        # has no sentence of its own.
        emit_progress(explain(reason) if _has_sentence(reason) else explain(code))
        emit_trace_event(
            "inputs_rejected",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        return {"status": AgentStatus.ERROR.value, "error_log": [code]}
