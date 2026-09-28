# PB-2 + PB-5: State Safety Verification
# Verifies that State contains only msgpack-safe types (no Pydantic, dataclass, JWT)
# and that the outer/inner State boundary of the approved Stage ② design holds:
#   - the outer State adds no domain field (caller-facing output stays inherited-only);
#   - the inner working fields live only on the inner State (no raw/working leak, no
#     partial register path to the outer, caller-facing State).

import ast
import os
import re
import pytest
import pathlib
from collections.abc import Iterator
from typing import Any


CREDENTIAL_FIELD_PATTERNS = re.compile(
    r"(jwt|token|api_key|secret|password|credential|connection_string)", re.IGNORECASE
)

PROHIBITED_TYPE_ANNOTATIONS = [
    "BaseModel",
    "InvocationContext",
]

STATE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "schemas", "state.py"
)

# Names of the outer and inner State classes in the approved design.
OUTER_STATE_CLASS = "State"
INNER_STATE_CLASS = "ScenarioWorkflowState"

# The domain working fields belong to the inner workflow State only. They must never be
# declared on the outer State — that is the schema-level guarantee that raw/working data
# and partial registers do not reach the caller-facing outer State.
INNER_WORKING_FIELDS = {
    "workflow_input",
    "resolved_rows",
    "extracted_values",
    "register_entries",
    "register",
}

# Identifiers allowed to appear in a msgpack-safe field annotation.
MSGPACK_SAFE_ANNOTATION_TOKENS = {
    "NotRequired",
    "Required",
    "Optional",
    "Any",
    "dict",
    "list",
    "tuple",
    "set",
    "str",
    "int",
    "float",
    "bool",
    "None",
    "Dict",
    "List",
    "Tuple",
}


def _scan_state_file(filepath: str) -> list[str]:
    """Scan a state definition file for safety violations."""
    with open(filepath, "r") as f:
        source = f.read()
        tree = ast.parse(source, filename=filepath)

    violations = []

    for node in ast.walk(tree):
        # Check class definitions that look like State
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    field_name = item.target.id

                    # Check for credential-like field names
                    if CREDENTIAL_FIELD_PATTERNS.search(field_name):
                        violations.append(
                            f"{filepath}:{item.lineno} — Credential-like field name: {field_name}"
                        )

                    # Check for prohibited type annotations
                    if item.annotation:
                        annotation_str = ast.dump(item.annotation)
                        for prohibited in PROHIBITED_TYPE_ANNOTATIONS:
                            if prohibited in annotation_str:
                                violations.append(
                                    f"{filepath}:{item.lineno} — Prohibited type in State: {prohibited}"
                                )

    return violations


def _state_classes(filepath: str) -> dict:
    """Parse the state file into {class_name: {"bases": [...], "fields": {name: annotation}}}."""
    with open(filepath, "r") as f:
        tree = ast.parse(f.read(), filename=filepath)

    classes: dict = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
        fields = {}
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                fields[item.target.id] = ast.unparse(item.annotation)
        classes[node.name] = {"bases": bases, "fields": fields}
    return classes


def _annotation_tokens(annotation: str) -> set:
    """Identifier tokens used in an annotation string."""
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", annotation))


class TestStateSafety:
    """PB-2/PB-5: State must be msgpack-safe with no credentials."""

    def test_state_file_safety(self):
        """State definition must not contain credential fields or prohibited types."""
        if not os.path.exists(STATE_FILE):
            pytest.skip("src/schemas/state.py not found")

        violations = _scan_state_file(STATE_FILE)

        assert violations == [], (
            "State safety violations found:\n" + "\n".join(violations)
        )


class TestScenarioStateSchema:
    """Focused checks for the approved Stage ② outer/inner State boundary."""

    def setup_method(self):
        if not os.path.exists(STATE_FILE):
            pytest.skip("src/schemas/state.py not found")
        self.classes = _state_classes(STATE_FILE)

    def test_both_states_subclass_agent_state(self):
        """Outer and inner State are flat TypedDicts composed on AgentState."""
        for name in (OUTER_STATE_CLASS, INNER_STATE_CLASS):
            assert name in self.classes, f"missing State class: {name}"
            assert self.classes[name]["bases"] == ["AgentState"], (
                f"{name} must subclass AgentState only, got {self.classes[name]['bases']}"
            )

    def test_outer_state_adds_no_domain_field(self):
        """The outer State adds no domain field — its one own field is the degradation marker,
        which carries an allow-listed code and never request or source content."""
        outer_fields = self.classes[OUTER_STATE_CLASS]["fields"]
        assert set(outer_fields) == {"diagnostic_code"}, (
            f"outer {OUTER_STATE_CLASS} must add no domain field, got {sorted(outer_fields)}"
        )

    def test_inner_working_fields_are_inner_only(self):
        """Working fields live on the inner State only — never on the caller-facing outer State."""
        inner_fields = set(self.classes[INNER_STATE_CLASS]["fields"])
        outer_fields = set(self.classes[OUTER_STATE_CLASS]["fields"])
        missing = INNER_WORKING_FIELDS - inner_fields
        assert not missing, f"inner State missing working fields: {sorted(missing)}"
        leaked = INNER_WORKING_FIELDS & outer_fields
        assert not leaked, f"working fields leaked onto the outer State: {sorted(leaked)}"

    def test_inner_fields_are_msgpack_safe(self):
        """Every inner domain field is annotated with msgpack-safe container/primitive types."""
        for name, annotation in self.classes[INNER_STATE_CLASS]["fields"].items():
            tokens = _annotation_tokens(annotation)
            unsafe = tokens - MSGPACK_SAFE_ANNOTATION_TOKENS
            assert not unsafe, (
                f"{INNER_STATE_CLASS}.{name} has non-msgpack-safe annotation "
                f"'{annotation}' (offending: {sorted(unsafe)})"
            )


# --- PB-5: pre-checkpoint ingress protection (conditional) ---
# PB-5 applies only after checkpointing is enabled in config/config.yaml and the
# installed agentcore exposes its pre-checkpoint ingress-protection hooks.
_RUNTIME_CONFIG_PATH = pathlib.Path(__file__).parents[2] / "config" / "config.yaml"


def _checkpointing_enabled() -> bool:
    """Read runtime checkpoint settings; absent config is a fleet-transition waiver."""
    if not _RUNTIME_CONFIG_PATH.exists():
        return False
    try:
        import yaml

        config = yaml.safe_load(_RUNTIME_CONFIG_PATH.read_text()) or {}
    except Exception:
        return False
    return bool(config.get("memory_enabled") or config.get("hitl", {}).get("enabled", False))


def _framework_ingress_protection_available() -> bool:
    """Fail closed to a waiver until both agentcore ingress hooks are importable."""
    try:
        from framework.graph.base_graph import BaseGraph
    except Exception:
        return False
    return all(hasattr(BaseGraph, hook) for hook in ("_sanitize_ingress", "_sanitize_resume_feedback"))


def _walk_checkpoint_surface(value: Any, path: str = "checkpoint") -> Iterator[tuple[str, Any]]:
    """Yield every persisted value/key without lossy object-to-string conversion."""
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_checkpoint_surface(key, f"{path}.<key>")
            yield from _walk_checkpoint_surface(child, f"{path}[{key!r}]")
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, child in enumerate(value):
            yield from _walk_checkpoint_surface(child, f"{path}[{index}]")


def _assert_raw_ingress_absent(surfaces: dict[str, Any], raw_values: dict[str, Any]) -> None:
    """Fail when raw ingress occurs exactly or embedded in a persisted string leaf/key."""
    for surface, value in surfaces.items():
        for path, persisted in _walk_checkpoint_surface(value, surface):
            for name, raw in raw_values.items():
                if raw in (None, "", {}, []):
                    continue
                if persisted == raw:
                    pytest.fail(f"PB-5 raw {name} found at {path}; ingress crossed persistence boundary")
                if isinstance(raw, str) and isinstance(persisted, str) and raw in persisted:
                    pytest.fail(f"PB-5 raw {name} found within string at {path}; ingress crossed persistence boundary")
                if isinstance(raw, dict):
                    for key, raw_value in raw.items():
                        if isinstance(raw_value, str) and isinstance(persisted, str) and raw_value in persisted:
                            pytest.fail(
                                f"PB-5 raw {name}[{key!r}] found within string at {path}; "
                                "ingress crossed persistence boundary"
                            )


_PB5_APPLICABLE = _checkpointing_enabled() and _framework_ingress_protection_available()
_PB5_WAIVER_REASON = (
    "config/config.yaml enables neither memory_enabled nor hitl.enabled — PB-5 auto-waived"
    if not _checkpointing_enabled()
    else "installed agentcore lacks BaseGraph ingress hooks — PB-5 auto-waived pending framework cutover"
)


@pytest.mark.skipif(not _PB5_APPLICABLE, reason=_PB5_WAIVER_REASON)
def test_pb5_precheckpoint_ingress_not_raw() -> None:
    """PB-5: inspect every persisted surface after unique PII-bearing ingress.

    TODO after agentcore capability cutover: build this template graph with its runtime
    checkpointer; invoke with unique user_input/input_context values; resume with unique
    feedback for HITL; then pass checkpoint, metadata, and pending_writes to the helper.
    Do not use json.dumps(..., default=str) or stringify unknown objects.
    """
    pytest.fail(
        "PB-5 is applicable (checkpointing enabled + framework ingress hooks present) but "
        "this template has not wired a graph/checkpointer fixture — see the TODO above. "
        "Build the fixture and call _assert_raw_ingress_absent() before shipping; once the "
        "capability that makes PB-5 apply is live, this must run the real assertion, not skip."
    )

    # checkpoint_tuple = checkpointer.get_tuple(config)
    # _assert_raw_ingress_absent(
    #     {"checkpoint": checkpoint_tuple.checkpoint,
    #      "metadata": checkpoint_tuple.metadata,
    #      "pending_writes": checkpoint_tuple.pending_writes},
    #     {"user_input": raw_user_input, "input_context": raw_input_context,
    #      "resume_feedback": raw_feedback},
    # )
