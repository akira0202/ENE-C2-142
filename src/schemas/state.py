"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel / dataclass /
# arbitrary Python object. LangGraph checkpoints use msgpack serialization, so only
# JSON-safe types are allowed (str / int / float / bool / None / list / dict).
# Do NOT add credentials, secrets, InvocationContext, client objects, or raw source blobs.

from typing import Any, NotRequired

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Outer State for MunicipalEnergyScenarioInputEvidenceExtractorGraph (Cat 2, L1-direct).

    Flat TypedDict — JSON-serializable types only. The outer graph adds NO domain field;
    the whole handoff uses inherited AgentState slots:
      - user_input: str   — JSON string carrying the three supplied inputs
      - validated_input   — parsed, contract-checked inputs (set by the outer pre_process)
      - result            — the assembled scenario-input register, mapped from the inner
                            graph by merge_output ONLY on success (register + status)
      - formatted_output  — the S-3-gated register; AgentBaseGraph.get_output() =
                            formatted_output or result
      - status, session_id, and the reducer-managed node_history / error_log (audit trail)

    The domain pipeline runs in ScenarioWorkflowState (below). On error no partial register
    is projected: merge_output maps only the inner get_output() dict (register + status),
    and the inner working fields never cross the boundary. node_history / error_log are
    reducer-managed and are NEVER projected inner -> outer. Raw source artifacts (the caller
    payload, manifest, worksheet) stay in the inherited user_input / validated_input slots and
    are never surfaced in result / formatted_output.

    One own field is added: ``diagnostic_code`` — an allow-listed, non-sensitive code naming why
    no register was produced. Absent on a normal run; set on a request the caller can correct or a
    register withheld by the output policy (src/services/degradation.py). It never carries request
    or source content.
    """

    diagnostic_code: str


class ScenarioWorkflowState(AgentState):
    """Inner State for the domain workflow graph inside the main GraphNode.

    Flat TypedDict — JSON-safe types only (no Pydantic / dataclass / InvocationContext /
    credentials / raw source blobs). Inherited from AgentState: user_input (the JSON string
    handed in by the outer GraphNode's extract_input), validated_input, status. The domain
    working fields below are set progressively by the inner nodes and never cross the outer
    boundary — only the terminal register + status, and the degradation marker, are surfaced by
    the inner get_output(). The marker has to travel this way: an inner node that errors is
    re-raised as SubgraphError before merge_output() runs, so a run the caller can correct
    completes instead and carries its code outward.
    """

    diagnostic_code: str

    # Hydrated inputs (extract rows, manifest, worksheet directives) parsed from the JSON
    # handoff. (set by input_hydrate)
    workflow_input: NotRequired[dict[str, Any]]
    # Extract rows resolved against the version manifest, each carrying its stamped
    # source_version and allowed provenance references. (set by manifest_extract_resolve)
    resolved_rows: NotRequired[list[dict[str, Any]]]
    # Worksheet-directed selected values, taken as supplied — never interpolated, estimated,
    # or unit-converted. (set by worksheet_value_extract)
    extracted_values: NotRequired[list[dict[str, Any]]]
    # Mapped entries carrying provenance and unit/time-coverage, plus per-entry
    # missing/ambiguous flags. (set by provenance_unit_coverage_map)
    register_entries: NotRequired[list[dict[str, Any]]]
    # The assembled seven-field scenario-input register; surfaced to the outer graph by the
    # inner get_output() as the terminal result. (set by scenario_register_assemble)
    register: NotRequired[dict[str, Any]]
