# PB: pipeline invoke order + provenance-register boundary.
#
# Proves the three boundary contracts docs/02 declares for the inner scenario-input workflow:
#   1. Order — validation (hydrate) precedes version resolution, extraction, mapping, and assembly,
#      and every non-terminal hop can short-circuit to END (fail-closed, no partial output).
#   2. Register boundary — only the allowlisted seven-field/provenance register (+ framework
#      metadata) crosses the inner→outer boundary; no inner working State is ever projected, even
#      when the State is polluted with every inner key.
#   3. No partial on failure — an inner error sub-result surfaces no register at the outer boundary.
#
# test_graph_composition.py asserts the node wiring; this module proves the BOUNDARY invariants hold
# (ordering + allowlist under adversarial pollution + no partial). Imports framework → runs in CI.

from langgraph.graph import END, START

from framework.schemas.agent_status import AgentStatus
from src.graph.domain_workflow_graph import ScenarioWorkflowGraph
from src.graph.graph import ScenarioExtractWorkflowGraphNode

# The domain pipeline order: validation → resolution → extraction → mapping → assembly.
_STAGE_ORDER = [
    "input_hydrate",
    "manifest_extract_resolve",
    "worksheet_value_extract",
    "provenance_unit_coverage_map",
    "scenario_register_assemble",
]
_INNER_WORKING = {"workflow_input", "resolved_rows", "extracted_values", "register_entries", "validated_input"}
_ALLOWED_SURFACE = {"register", "status", "diagnostic_code", "error_log", "correlation_id", "node_history"}


class _EdgeRecorder:
    """Capture the inner graph's declared edges without a live langgraph StateGraph."""

    def __init__(self) -> None:
        self.entry: list = []                 # START → node
        self.terminal: list = []              # node → END (unconditional)
        self.hops: list[tuple] = []           # (src, continue_target, end_target)

    def add_edge(self, a, b) -> None:
        if a is START:
            self.entry.append(b)
        elif b is END:
            self.terminal.append(a)

    def add_conditional_edges(self, src, _fn, mapping) -> None:
        self.hops.append((src, mapping.get("continue"), mapping.get("end")))


def _record_edges() -> _EdgeRecorder:
    inner = ScenarioWorkflowGraph(config={})
    rec = _EdgeRecorder()
    inner._sg = rec  # capture the wiring add_edges() declares, no compile needed
    inner.add_edges()
    return rec


def _seven_field_register() -> dict:
    entry = {
        "geography": "shibata-city", "time_coverage": "2030-annual", "energy_type": "electricity",
        "unit": "GWh", "source_version": "2025.1", "value_selection_rule": "latest approved",
        "missing_or_ambiguous": None, "value": 1.5, "source_id": "jed",
    }
    return {"entries": [entry], "entry_count": 1, "flagged_count": 0}


# ── 1. invoke order ──────────────────────────────────────────────────────────
def test_validation_precedes_resolution_extraction_mapping_assembly():
    rec = _record_edges()
    # the graph enters at the validation/hydrate node
    assert rec.entry == ["input_hydrate"]
    # reconstruct the linear continue-chain and assert the full ordered pipeline
    cont = {src: c for src, c, _e in rec.hops}
    chain = ["input_hydrate"]
    while chain[-1] in cont:
        chain.append(cont[chain[-1]])
    assert chain == _STAGE_ORDER
    # the terminal stage closes to END
    assert rec.terminal == ["scenario_register_assemble"]


def test_every_hop_short_circuits_to_end_no_partial():
    rec = _record_edges()
    # every non-terminal hop has an explicit END branch: an error routes out with no partial output
    assert rec.hops, "no conditional hops recorded"
    for src, _cont, end in rec.hops:
        assert end is END, f"{src} cannot short-circuit to END"
    # and the predicate: error → end, success → continue
    inner = ScenarioWorkflowGraph(config={})
    assert inner._continue_or_end({"status": AgentStatus.ERROR.value}) == "end"
    assert inner._continue_or_end({"status": AgentStatus.SUCCESS.value}) == "continue"


# ── 2. register boundary (allowlist under pollution) ─────────────────────────
def test_inner_get_output_surfaces_only_allowlisted_register():
    inner = ScenarioWorkflowGraph(config={})
    polluted = {k: "MUST_NOT_LEAK" for k in _INNER_WORKING}
    polluted.update({
        "register": _seven_field_register(), "status": AgentStatus.SUCCESS.value,
        "correlation_id": "pb", "error_log": [], "node_history": [],
    })
    out = inner.get_output(polluted)
    assert set(out) <= _ALLOWED_SURFACE
    assert not (_INNER_WORKING & set(out))
    assert out["register"] == polluted["register"]


def test_merge_output_projects_only_register_and_status():
    node = ScenarioExtractWorkflowGraphNode()
    sub = {"register": _seven_field_register(), "status": AgentStatus.SUCCESS.value}
    sub.update({k: "MUST_NOT_LEAK" for k in _INNER_WORKING})
    out = node.merge_output({}, sub)
    assert set(out) == {"result", "status", "diagnostic_code"}
    assert out["result"] == sub["register"]
    assert not (_INNER_WORKING & set(out))


# ── 3. no partial register on failure ────────────────────────────────────────
def test_merge_output_on_inner_error_surfaces_no_register():
    node = ScenarioExtractWorkflowGraphNode()
    # an inner error (missing / mismatched / unknown-version) yields a sub-result with no register
    out = node.merge_output({}, {"status": AgentStatus.ERROR.value, "error_log": ["ERR_VERSION_MISMATCH"]})
    assert out["result"] is None
    assert out["status"] == AgentStatus.ERROR.value
    assert not (_INNER_WORKING & set(out))
