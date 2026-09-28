"""AgentCore Platform v1.0 — OutputGateNode for ENE-C2-142 (outer post_process).

Node contract:
 - Extend FunctionNode; implement execute(state) -> dict; extend S-3 via _extra_security_gate_output.
 - Return ONLY the fields this node changes (never {**state}).
 - Return AgentStatus.<X>.value strings — never the bare Enum object.
 - Never import from mediator/, api/, src/graph/, or other agents.

Responsibility (docs/02 — outer post_process / OutputGateNode):
 - Terminal output gate over the assembled scenario-input register: formats result into
   formatted_output and enforces S-3 output safety and the advisory/read-only boundary.
 - Outer boundary node — required_trust_level is VERIFIED_EXTERNAL.
"""

from typing import Any, ClassVar, cast

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from framework.security.pii_masking import mask_pii
from shared.security.pii_detector import detect_pii
from shared.utils.audit_logger import emit_trace_event

from src.services.degradation import REGISTER_WITHHELD, explain_degradation
from src.services.output_policy import mask_residual_jp_names, scan_prohibited
from src.services.register_assembly import is_valid_register
from src.services.progress import emit_progress
from src.services.failure_message import explain

# Fail-closed code for a missing / malformed register reaching the output gate.
ERR_OUTPUT_INPUT = "ERR_OUTPUT_INPUT"


def _has_sentence(reason: str) -> bool:
    """True when `reason` resolves to a sentence of its own rather than the general fallback."""
    return explain(reason) != explain("__no_such_code__")


class OutputGateNode(FunctionNode):
    """Outer post_process node — terminal S-3 output gate: enforce the advisory/read-only boundary
    and mask personal names before the register leaves the agent."""

    # S-1 (docs/02 §Trust boundary): the outer boundary requires a verified external caller.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emit_progress("Preparing the response...")
        # Already answered upstream: no register exists by design. The output is the reason alone,
        # not the register shape with zero entries — an empty register reads as "extracted, nothing
        # found", which is the opposite of what happened. Every value is a constant, so nothing the
        # refused request carried reaches the caller.
        degraded_code = state.get("diagnostic_code")
        if degraded_code:
            emit_trace_event(
                "register_degraded",
                {"correlation_id": state.get("correlation_id"), "code": degraded_code},
                state,
            )
            return self._notice(str(degraded_code))
        result: Any = state.get("result")
        # A missing / malformed register is a structural anomaly (broken projection or wiring) —
        # fail closed, never degrade it to an empty success at the caller-facing boundary.
        if not is_valid_register(result):
            return self._reject(state, ERR_OUTPUT_INPUT, "missing_or_malformed_result")
        # Advisory/read-only boundary — the register is evidence, never an operational directive.
        # Fail closed HERE (no formatted_output) rather than raising from the S-3 hook, so a blocked
        # register is never published: nothing sets formatted_output on this path.
        category = scan_prohibited(result)
        if category is not None:
            # A scope-policy matter, not a security failure: withhold the whole register and
            # complete with the fixed notice. Only the category slug is recorded.
            emit_trace_event(
                "register_withheld",
                {"correlation_id": state.get("correlation_id"), "reason": f"prohibited_{category}"},
                state,
            )
            return self._notice(REGISTER_WITHHELD)
        emit_trace_event(
            "output_gated",
            {"correlation_id": state.get("correlation_id"), "entry_count": result["entry_count"]},
            state,
        )
        return {"formatted_output": result, "status": AgentStatus.SUCCESS.value}

    def _notice(self, code: str) -> dict[str, Any]:
        """Complete the run with the fixed notice for ``code`` and no register. The code is carried
        in this node's own dict as well as in State, so the response and the audit trail name the
        same code. ``result`` is cleared because AgentBaseGraph.get_output() is
        ``formatted_output or result``."""
        return {
            "diagnostic_code": code,
            "result": None,
            "formatted_output": explain_degradation(code),
            "status": AgentStatus.SUCCESS.value,
        }

    # --- fail-closed helper: owned delta only; code in error_log, slug in the trace event ---
    def _reject(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # `reason` names the specific cause (malformed_json, too_deep, ...) while `code` is the
        # coarse contract bucket the run fails under. Explaining the code alone collapses every
        # rejection to one sentence, so prefer the reason and fall back to the code only when it
        # has no sentence of its own.
        emit_progress(explain(reason) if _has_sentence(reason) else explain(code))
        emit_trace_event(
            "output_gate_rejected",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        # Clear result too: AgentBaseGraph.get_output() is `formatted_output or result`, so an
        # un-published (blocked/malformed) register would still leak via the result fallback unless
        # it is cleared here. Fail closed = no register surfaced on any output-gate reject.
        return {"status": AgentStatus.ERROR.value, "error_log": [code], "result": None}

    # --- S-3 domain output gate (runs after the framework's default credential scan) ---------
    # Personal-name output masking: S-3 performs NO PII masking automatically (the framework default checks
    # credentials only), so output-side personal-name masking is done here. The labelled
    # Kanji/Katakana case (氏名/名前/担当者) is the framework substrate's REAL capability — reuse
    # detect_pii()/mask_pii() (never hand-rolled). The residual gap (honorific-anchored names and
    # the お名前/申請者 labels) is masked with the pure-re Pattern B helper. Credentials remain the
    # framework default S-3 scan's job.
    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        # Output-side personal-name masking (execute() already fail-closed the advisory/read-only
        # prohibition, and the framework default S-3 scans credentials).
        return cast(dict[str, Any], self._mask_tree(result))

    def _mask_text(self, text: str) -> str:
        findings = detect_pii(text)  # substrate: Latin name + labelled Kanji/Katakana name_jp
        if findings:
            text = mask_pii(text, findings)
        text, _ = mask_residual_jp_names(text)  # residual gap: honorific / お名前 / 申請者
        return text

    def _mask_tree(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._mask_text(value)
        if isinstance(value, dict):
            return {k: self._mask_tree(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._mask_tree(v) for v in value]
        if isinstance(value, tuple):
            return tuple(self._mask_tree(v) for v in value)
        return value
