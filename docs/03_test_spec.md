# Test Specification

## Test Strategy

- **Test types**: Unit (framework-free service logic + per-node + State + graph wiring),
  Proof-of-Boundary (framework contract), Integration (compiled-graph `agent.invoke()` E2E).
- **Layering**: the deterministic domain logic lives in framework-free `src/services/*` modules, unit
  tested locally; the framework-importing node / graph tests and the E2E invoke run in CI. The E2E
  suite `importorskip`s the framework runtime, so it skips cleanly off-runtime and runs in CI.
- **Coverage**: line coverage **is collected and reported** by `run-tests` (`pytest --cov=src
  --cov-report=term`); the `--cov-fail-under` **threshold is advisory during rollout** (the coverage
  pass is non-blocking — a below-floor result warns, it does not fail the job). The acceptance evidence
  for this template is a **green `run-tests` + `gate-stub-check`** plus the mandatory TC / PB / BL
  matrices below, each traced to a real test function; the reported coverage is supporting evidence.
- **Determinism**: the v1 core path is supplied-only / deterministic / offline (no LLM, DB, vector
  store, or external API), so every case below is reproducible without live infrastructure.

## Outcome Contract (traced from `docs/02` §v1 Source of Truth / Flag-versus-error)

This template has exactly **three terminal outcomes** (`docs/02` §Flag-versus-error) and produces a
**single output kind** — the seven-field scenario-input register. Data gaps within otherwise-valid
inputs are **flagged inside the register** (they do not fail the run).

| Outcome | Trigger | Terminal State |
|---------|---------|----------------|
| **Safe register** | every stage passes; per-directive gaps are recorded as `missing_or_ambiguous` reason codes | `status = success`; `formatted_output` carries the seven-field register with per-entry value / provenance and `missing_or_ambiguous` flags |
| **Completed without a register (notice)** | a request the caller can correct — input-contract violation (`InputIntakeNode`) or extract↔manifest version / dataset mismatch (`ManifestExtractResolveNode`) — or a register withheld by the output policy (`OutputGateNode`) | `status = success`, `diagnostic_code` = the allow-listed code, `result = None`, `formatted_output` = the fixed notice for it; **no register and no request content** |
| **Fail-closed (no output)** | S-2 structural screen; broken outer→inner handoff (`InputHydrateNode`); the structural input contracts between the inner nodes; a malformed/inconsistent register; credential-shaped content (framework S-3) | `status = error`, `result = None`, `formatted_output = None`; **no caller-facing register, no partial output**; `error_log` carries only a non-sensitive code |

Because the `main` GraphNode uses `error_strategy = "propagate"`, any inner *failure* ends the run
with no output; a caller-correctable rejection completes instead, which is the only way an inner
node's code can reach the caller. The register is returned only when the whole pipeline passes and
the output gate clears it.

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Traced test(s) |
|-------|------|----------------|----------------|
| TC-01 | State contract: flat TypedDict, JSON/msgpack-safe only | No Pydantic/dataclass; primitives/containers only; outer adds no domain field; inner working fields inner-only | `tests/proof_of_boundary/test_state_safety.py::test_both_states_subclass_agent_state`, `::test_outer_state_adds_no_domain_field`, `::test_inner_working_fields_are_inner_only`, `::test_inner_fields_are_msgpack_safe` |
| TC-02 | Invalid input / insufficient trust fails closed | S-1 refuses `ANONYMOUS` before `execute()`; contract violations → `status:error` | `tests/unit/test_input_intake_node.py::test_s1_required_trust_level_is_verified_external`; `tests/integration/test_graph_invoke_e2e.py::test_invoke_anonymous_is_refused`; the BL-02–07 input-contract cases |
| TC-03 | No JWT / credential in State or the repo | CI `gate-credential-scan`: 0 violations | CI job `gate-credential-scan` (pipeline gate; no in-repo test) |
| TC-04 | `InvocationContext` not stored in State; accessed via `from_state()` | State declares no `input_context` / `invocation_context` field; nodes never construct it directly | `tests/proof_of_boundary/test_state_safety.py::test_inner_fields_are_msgpack_safe` (prohibited-annotation scan incl. `InvocationContext`) |
| TC-05 | S-4: no duplicate lifecycle events inside `execute()` | `node_start`/`node_complete`/`node_error` not emitted inside `execute()`; domain event where asserted (S-4 map) | See the **S-4 event evidence map** below |
| TC-06 | S-2: `_security_gate_input()` is `@final` (not overridable) | `TypeError` at class definition if overridden | `tests/unit/test_framework_compliance_tc06_tc07.py::test_tc06_security_gate_input_cannot_be_overridden` |
| TC-07 | S-3: `_security_gate_output()` is `@final` (not overridable) | `TypeError` at class definition if overridden | `tests/unit/test_framework_compliance_tc06_tc07.py::test_tc07_security_gate_output_cannot_be_overridden` |
| TC-08 | `required_trust_level` declared per node and enforced at `__call__` | Every `FunctionNode` declares it; outer boundary `VERIFIED_EXTERNAL`, inner `ANONYMOUS`; insufficient trust refused | CI `gate-trust-level-check`; `tests/unit/test_input_intake_node.py::test_s1_required_trust_level_is_verified_external`, `tests/unit/test_manifest_extract_resolve_node.py::test_s1_required_trust_level_is_anonymous`; `tests/integration/test_graph_invoke_e2e.py::test_invoke_anonymous_is_refused` |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial (structural screen) | Domain structural screen (non-`str` / NUL / control-char / oversized) runs in the hook; the framework baseline PII scan still runs | `tests/unit/test_input_intake_node.py::test_s2_gate_rejects_nul_byte`, `::test_s2_gate_passes_clean_payload`, `::test_s2_gate_passes_through_missing_input`; `tests/unit/test_input_schema.py::test_structural_screen_rejects_unsafe`, `::test_structural_screen_accepts_clean_json_string` |
| TC-10 | S-3: domain output safety present | `OutputGateNode` enforces the advisory/read-only prohibition fail-closed in `execute()` and masks personal names in `_extra_security_gate_output()`; the framework default S-3 scans credentials | `tests/unit/test_output_gate_node.py::test_output_gate_fails_closed_on_prohibited_directive`, `::test_output_gate_masks_residual_name`; `tests/unit/test_output_policy.py` (all) |
| TC-11 | S-4: ≥1 domain `emit_trace_event()` inside each `execute()` | Domain event emitted in `execute()` on both success and reject, for every node | `tests/proof_of_boundary/test_pb1_domain_audit_events.py` (all nodes, both paths); per-node success spies in the **S-4 event evidence map**; framework lifecycle order by `tests/proof_of_boundary/test_pb_invoke_order.py::test_call_order_for_every_node` |

### S-4 event evidence map

The framework `node_start` / `node_complete` lifecycle is covered for **every** node by PB-6. Each
node's **domain** event is independently spied on **both** its success and its fail-closed reject
path. The **reject** events for all seven nodes — and **both** paths of `InputHydrateNode` (which has
no dedicated unit test) — are proven by the PB-1 audit-event module
`tests/proof_of_boundary/test_pb1_domain_audit_events.py`, which also asserts the reject delta carries
no register fragment and no inner-working State.

- **`InputIntakeNode`** — success (`inputs_validated`): `tests/unit/test_input_intake_node.py::test_valid_input_emits_validated_input`;
  reject (`inputs_rejected`): `::test_malformed_json_rejected` and `tests/proof_of_boundary/test_pb1_domain_audit_events.py::test_every_node_emits_domain_event_on_reject[InputIntakeNode]`
- **`ManifestExtractResolveNode`** — success (`extract_resolved`): `tests/unit/test_manifest_extract_resolve_node.py::test_valid_resolution_emits_resolved_rows`;
  reject (`extract_resolve_rejected`): `tests/proof_of_boundary/test_pb1_domain_audit_events.py::test_every_node_emits_domain_event_on_reject[ManifestExtractResolveNode]`
- **`WorksheetValueExtractNode`** — success (`values_extracted`): `tests/unit/test_worksheet_value_extract_node.py::test_valid_extraction_emits_extracted_values`;
  reject (`value_extract_rejected`): `tests/proof_of_boundary/test_pb1_domain_audit_events.py::test_every_node_emits_domain_event_on_reject[WorksheetValueExtractNode]`
- **`ProvenanceUnitCoverageMapNode`** — success (`provenance_mapped`): `tests/unit/test_provenance_unit_coverage_map_node.py::test_valid_mapping_emits_register_entries`;
  reject (`provenance_map_rejected`): `tests/proof_of_boundary/test_pb1_domain_audit_events.py::test_every_node_emits_domain_event_on_reject[ProvenanceUnitCoverageMapNode]`
- **`ScenarioRegisterAssembleNode`** — success (`register_assembled`): `tests/unit/test_scenario_register_assemble_node.py::test_valid_assembly_emits_register`;
  reject (`register_assemble_rejected`): `tests/proof_of_boundary/test_pb1_domain_audit_events.py::test_every_node_emits_domain_event_on_reject[ScenarioRegisterAssembleNode]`
- **`OutputGateNode`** — success (`output_gated`): `tests/unit/test_output_gate_node.py::test_execute_formats_result_and_emits_trace`;
  reject (`output_gate_rejected`): `tests/proof_of_boundary/test_pb1_domain_audit_events.py::test_every_node_emits_domain_event_on_reject[OutputGateNode]`
- **`InputHydrateNode`** — success (`hydrate`): `tests/proof_of_boundary/test_pb1_domain_audit_events.py::test_input_hydrate_emits_domain_event_on_success`;
  reject (`hydrate_rejected`): `::test_every_node_emits_domain_event_on_reject[InputHydrateNode]`
- **All nodes** — framework `node_start` → … → `node_complete` presence and order:
  `tests/proof_of_boundary/test_pb_invoke_order.py::test_call_order_for_every_node`.

> **Scope note:** TC-05 / TC-11 / PB-1 domain-event evidence covers every node on both its success and
> reject paths (see the module above); no path remains `[assertion pending]`.

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Expected Result | Traced test(s) |
|-------|----------|----------------|----------------|
| PB-1 | BaseNode → AuditLogger | Framework lifecycle events fire for every node (no silent failures); each node emits its **domain** event on both success and reject | `tests/proof_of_boundary/test_pb_invoke_order.py::test_call_order_for_every_node` (lifecycle order); `tests/proof_of_boundary/test_pb1_domain_audit_events.py` (domain events, both paths); see the **S-4 event evidence map** |
| PB-2 | State serialization | Post-invoke State is primitives/JSON-safe only | `tests/proof_of_boundary/test_state_safety.py::test_state_file_safety`, `::test_inner_fields_are_msgpack_safe` |
| PB-3 | L1 → External service | **N/A — no external service in scope.** v1 is supplied-only / deterministic / offline: no LLM, DB, vector store, or external API on the core path (`docs/02` §Framework Utilization: ConnectionPolicy not required). No external boundary exists to exercise; the deterministic path is covered by PB-6 and the BL cases. | — (N/A) |
| PB-4 | Import isolation | AST scan: 0 Level-0 imports | `tests/proof_of_boundary/test_import_isolation.py::test_no_prohibited_imports_in_src` |
| PB-5 | Checkpoint safety | Saved-State shape carries no JWT/Pydantic/raw object | `tests/proof_of_boundary/test_state_safety.py::test_state_file_safety`, `::test_inner_fields_are_msgpack_safe` |
| PB-6 | Invoke execution order | Per node `__call__()`: S-1 → S-4 `node_start` → S-2 `_security_gate_input` → `execute()` → S-3 `_security_gate_output` → S-4 `node_complete`. Pipeline order: validation (hydrate) precedes resolution → extraction → mapping → assembly, each hop short-circuiting to END on error | `tests/proof_of_boundary/test_pb_invoke_order.py::test_call_order_for_every_node` (per-node order); `tests/proof_of_boundary/test_pb_invoke_order_and_register.py::test_validation_precedes_resolution_extraction_mapping_assembly`, `::test_every_hop_short_circuits_to_end_no_partial` (pipeline order) |
| PB-7 | HITL interrupt propagation *(conditional)* | **Auto-waived — non-HITL.** `config/agent.yaml` declares no `hitl.enabled: true` and the template provisions no checkpointer; `docs/01` / `docs/02` declare a read-only, non-HITL, deterministic template. The scaffold PB-7 test auto-skips (`skipif`) when HITL is not enabled. | `tests/proof_of_boundary/test_pb7_hitl_interrupt_propagation.py` (auto-skipped — non-HITL) |

> **PB gate checklist:** PB-1, PB-2, PB-4, PB-5, PB-6 are mandatory and covered above. **PB-3 is N/A**
> (no external service in scope). **PB-7 is Auto-waived — non-HITL** and must not block the gate.

## Business Logic Tests

> Acceptance tests traced from `docs/02`: the fail-closed input-contract codes (BL-02–07), the
> in-register data-gap flags (BL-08–12), the recording-only selection-rule boundary (BL-12), the
> terminal output gate (BL-13–15), the graph projection / no-leak contract (BL-16), and the
> caller-boundary invoke outcomes (BL-17). Each row cites the specific `file::test_function`.

| BL-ID | Test | Input | Expected Result | Traced test(s) |
|-------|------|-------|----------------|----------------|
| BL-01 | Safe success — a matched directive yields a conformant register entry | valid three inputs; a worksheet directive matching one resolved extract row | `status = success`; register entry carries the supplied value (as-is), `source_version`, and `missing_or_ambiguous = None` | `tests/unit/test_value_extraction.py::test_conformant_takes_supplied_value_as_is`; `tests/unit/test_register_assembly.py::test_conformant_entry_serializes_seven_fields_and_provenance`; `tests/integration/test_graph_invoke_e2e.py::test_invoke_valid_publishes_register` |
| BL-02 | Missing required input → fail-closed | payload missing `municipality` / `jed_extract` / `version_manifest` / `worksheet` | `ERR_MISSING_INPUT`, `status = error`, no output | `tests/unit/test_input_schema.py::test_missing_required_input`; `tests/unit/test_input_intake_node.py::test_missing_input_rejected` |
| BL-03 | Municipality invalid (not one non-empty string) → fail-closed | empty / whitespace / non-string / list `municipality` | `ERR_MUNICIPALITY`, `status = error`, no output | `tests/unit/test_input_schema.py::test_municipality_must_be_one_nonempty_string`; `tests/unit/test_input_intake_node.py::test_municipality_rejected` |
| BL-04 | Malformed / schema violation → fail-closed | malformed JSON; missing column; unknown top-level or nested key; non-finite value; control char; blob coverage | `ERR_SCHEMA`, `status = error`, no `validated_input`, no output; no raw payload echoed | `tests/unit/test_input_schema.py::test_payload_not_object`, `::test_extract_missing_column`, `::test_extract_unknown_column_rejected`, `::test_top_level_unknown_key_rejected`, `::test_extract_value_must_be_finite_number`, `::test_control_character_in_cell_rejected`, `::test_coverage_rejects_non_finite_number`, `::test_coverage_rejects_over_deep_nesting`, `::test_coverage_rejects_non_json_type`; `tests/unit/test_input_intake_node.py::test_malformed_json_rejected`, `::test_reject_does_not_echo_payload` |
| BL-05 | Version mismatch / unknown / superseded → fail-closed (no fallback) | an extract row whose `source_version` ≠ manifest `dataset_version` (any old / unknown / superseded value) | `ERR_VERSION_MISMATCH`, `status = error`, no partial resolution; no fallback to an older version | `tests/unit/test_manifest_resolution.py::test_version_mismatch_fails_closed`, `::test_no_fallback_when_any_row_is_old_version`; `tests/unit/test_manifest_extract_resolve_node.py::test_version_mismatch_rejected`; `tests/integration/test_graph_invoke_e2e.py::test_invoke_inner_version_mismatch_fails_closed` |
| BL-06 | Dataset cross-reference mismatch → fail-closed | an extract row whose `dataset_id` ≠ manifest `dataset_id` | `ERR_DATASET_MISMATCH`, `status = error`, no output | `tests/unit/test_manifest_resolution.py::test_dataset_id_mismatch_fails_closed` |
| BL-07 | Manifest / extract metadata schema mismatch → fail-closed | manifest missing `dataset_id` / `dataset_version`; extract row missing `source_version` / `dataset_id`; non-dict workflow; empty extract | `ERR_MANIFEST_SCHEMA`, `status = error`, no output | `tests/unit/test_manifest_resolution.py::test_manifest_missing_dataset_version`, `::test_manifest_missing_dataset_id`, `::test_row_missing_source_version`, `::test_row_missing_dataset_id`, `::test_non_dict_workflow`, `::test_empty_extract` |
| BL-08 | Missing extraction (requested value absent) → flagged, not failed | a worksheet directive with no matching resolved row | register entry with `missing_or_ambiguous = value_absent`, `value = None`; `status = success` | `tests/unit/test_value_extraction.py::test_missing_reference_flagged_no_value`; `tests/unit/test_provenance_mapping.py::test_missing_absent_when_no_matching_row` |
| BL-09 | Ambiguous extraction (multiple candidates) → flagged, no candidate chosen | a directive matching more than one resolved row | register entry with `missing_or_ambiguous = multiple_candidates`, `value = None`; no candidate selected even with a rule present | `tests/unit/test_value_extraction.py::test_ambiguous_reference_chooses_nothing`; `tests/unit/test_provenance_mapping.py::test_ambiguous_maps_multiple_candidates`; `tests/unit/test_worksheet_value_extract_node.py::test_ambiguous_reference_chooses_nothing` |
| BL-10 | Unknown / unresolvable unit → flagged, never converted | a directive requesting a unit for which only a different unit is present | `missing_or_ambiguous = unresolvable_unit`, `value = None`; no unit conversion | `tests/unit/test_value_extraction.py::test_unit_mismatch_is_missing_never_converted`; `tests/unit/test_provenance_mapping.py::test_missing_unresolvable_unit_never_converted`; `tests/unit/test_provenance_unit_coverage_map_node.py::test_unit_mismatch_flagged_not_converted` |
| BL-11 | Coverage gap (period only partially covered) → flagged | a directive whose `(geography, energy_type)` exists only for a different `time_coverage` | `missing_or_ambiguous = coverage_gap`, `value = None` | `tests/unit/test_provenance_mapping.py::test_missing_coverage_gap_when_only_other_period_present` |
| BL-12 | Recording-only selection rule; status consumed verbatim | a worksheet `value_selection_rule`; a mapping result carrying a `missing_or_ambiguous` reason | the rule is recorded verbatim (never applied to choose); assembly consumes the mapping status without re-evaluation; a corrupt upstream status/flag fails closed | `tests/unit/test_value_extraction.py::test_ambiguous_reference_chooses_nothing`; `tests/unit/test_register_assembly.py::test_flag_status_consumed_verbatim_not_re_evaluated`; `tests/unit/test_provenance_mapping.py::test_unknown_extraction_status_fails_closed`, `::test_status_invariant_violations_fail_closed` |
| BL-13 | Output gate blocks a prohibited / read-only-boundary directive | an assembled register whose free text carries a control / dispatch / trading / tariff / optimization / forecast **directive** | `OutputGateNode` fail-closed in `execute()`: `ERR_PROHIBITED_OUTPUT`, `status = error`, `result` / `formatted_output = None`, no output; analytical topic mentions are **not** flagged | `tests/unit/test_output_policy.py::test_control_instruction_flagged`, `::test_dispatch_trading_tariff_optimization_forecast_directives_flagged`, `::test_topic_mentions_not_flagged`; `tests/unit/test_output_gate_node.py::test_output_gate_fails_closed_on_prohibited_directive`; `tests/integration/test_graph_invoke_e2e.py::test_invoke_prohibited_directive_blocked_at_output_gate` |
| BL-14 | Output-side personal-name masking | a register free-text field carrying a labelled / honorific Japanese personal name | labelled Kanji/Katakana names masked via the shared detector; residual honorific / お名前 / 申請者 names masked; politeness (お客様) and substrate-labelled cases left to the shared detector | `tests/unit/test_output_gate_node.py::test_output_gate_masks_residual_name`; `tests/unit/test_output_policy.py::test_honorific_name_masked`, `::test_residual_label_masked`, `::test_substrate_labels_left_to_detect_pii`, `::test_politeness_not_masked` |
| BL-15 | Output boundary: malformed / inconsistent register → fail-closed, `result` cleared | a missing / non-dict / empty register; wrong-type or inconsistent counts; entry missing a field; value↔flag inconsistency | `ERR_OUTPUT_INPUT`, `status = error`, no `formatted_output`, `result = None` (no register surfaced via the `formatted_output or result` fallback) | `tests/unit/test_register_assembly.py::test_is_valid_register_accepts_assembled_output`, `::test_is_valid_register_rejects_inconsistent`; `tests/unit/test_output_gate_node.py::test_missing_or_malformed_result_fails_closed`, `::test_valid_flagged_register_passes` |
| BL-16 | Graph projection: inner working State never crosses the boundary | inner State polluted with `workflow_input` / `resolved_rows` / `extracted_values` / `register_entries` / `validated_input`; an inner-error sub-result with no register | inner `get_output()` and `merge_output()` surface only the allowlisted `register` → `result` + `status`; no inner working field projected; an inner error surfaces no register | `tests/unit/test_graph_composition.py::test_inner_get_output_is_allowlisted`, `::test_merge_output_maps_only_register_and_status`; `tests/proof_of_boundary/test_pb_invoke_order_and_register.py::test_inner_get_output_surfaces_only_allowlisted_register`, `::test_merge_output_projects_only_register_and_status`, `::test_merge_output_on_inner_error_surfaces_no_register` |
| BL-17 | Caller-boundary `agent.invoke()` outcomes | valid + `VERIFIED_EXTERNAL`; `ANONYMOUS` caller; inner-node error; prohibited output | valid → `status = success`, register published; `ANONYMOUS` → refused, no register; inner error → `SubgraphError` → outer finalize (post_process skipped), no output / no leak; prohibited → no register | `tests/integration/test_graph_invoke_e2e.py::test_invoke_valid_publishes_register`, `::test_invoke_anonymous_is_refused`, `::test_invoke_inner_version_mismatch_fails_closed`, `::test_invoke_prohibited_directive_blocked_at_output_gate` |
| BL-18 | No-action boundary: no external / prohibited-domain-action path exists | the agent execution surface (`src/graph` / `src/nodes` / `src/services` / `src/schemas`) | every import resolves to the deterministic allowlist (no network / subprocess / egress module); no `eval` / `exec` / `subprocess` / `socket` / `os.system` call site; no forecast / optimization / tariff / dispatch / trading / grid-control capability is defined (those verbs are deny-list detection literals only) | `tests/proof_of_boundary/test_pb_no_action_boundary.py::test_agent_runtime_imports_are_deterministic_allowlist`, `::test_no_external_action_or_side_effect_call_sites`, `::test_no_prohibited_domain_action_capability_defined`; deny-list detection by `tests/unit/test_output_policy.py::test_dispatch_trading_tariff_optimization_forecast_directives_flagged` |
| BL-19 | S-2 rejection prevents inner processing | an untrusted input carrying a control character (NUL) | the outer S-2 gate rejects at `pre_process`; `status = error`; no register is produced or projected — inner processing never runs | `tests/integration/test_graph_invoke_e2e.py::test_invoke_s2_unsafe_input_is_refused_before_inner_processing`; gate unit proof `tests/unit/test_input_intake_node.py::test_s2_gate_rejects_nul_byte` |
| BL-20 | No raw input / credentials / `InvocationContext` projected to the caller | a valid invoke | the caller output carries no `user_input` / inner working channel, no credential-like key, no `InvocationContext` object, and no verbatim echo of the raw request; the reject path likewise echoes no payload | `tests/integration/test_graph_invoke_e2e.py::test_invoke_projects_no_raw_input_credentials_or_context`; schema-level guarantees `tests/proof_of_boundary/test_state_safety.py::test_state_file_safety`, `::test_outer_state_adds_no_domain_field`; reject non-echo `tests/unit/test_input_intake_node.py::test_reject_does_not_echo_payload` |
| BL-21 | Caller-correctable rejection completes with its notice | plain-text request; missing input; extract row whose `source_version` disagrees with the manifest | `status = success` + the code, output = the fixed notice for it, no register; the steps after the one that set it do not run | `tests/unit/test_input_intake_node.py` (the `_assert_rejected` cases), `tests/unit/test_manifest_extract_resolve_node.py::test_version_mismatch_degrades`; `tests/integration/test_graph_invoke_e2e.py::test_invoke_plain_text_request_returns_the_notice`, `::test_invoke_inner_version_mismatch_returns_the_notice` |
| BL-22 | Withheld register | assembled register carrying a control/dispatch/trading/tariff/optimization/forecast directive | `status = success` + `REGISTER_WITHHELD`, `result` cleared, output = the fixed notice; no register content in the response | `tests/unit/test_output_gate_node.py::test_output_gate_withholds_a_prohibited_directive`; `tests/integration/test_graph_invoke_e2e.py::test_invoke_prohibited_directive_withheld_at_output_gate` |
| BL-23 | Defects and gate refusals stay errors | empty inner handoff; missing `workflow_input`; malformed register; NUL-carrying input | `status = error`, no output, no notice | `tests/proof_of_boundary/test_pb1_domain_audit_events.py::test_every_node_emits_domain_event_on_reject`; `tests/unit/test_manifest_extract_resolve_node.py::test_missing_workflow_input_fails_closed`; `tests/unit/test_output_gate_node.py::test_missing_or_malformed_result_fails_closed` |
| BL-24 | The notices themselves | every allow-listed code | each notice is its own sentence derived from the code alone, passes the same output policy a register must pass, and carries no request or source content | `tests/unit/test_degradation.py` (all) |

## Additional Regression Coverage

Guards added alongside the changes in this revision. Each entry names the test and the
condition it accepts on; they supplement the mandatory TC / PB items above and replace none
of them.

| Concern | Test | Acceptance condition |
|---|---|---|
| Deployment startup contract | `tests/unit/test_entry_point_import.py` | `src/api/server.py` — the module `uvicorn src.api.server:app` loads — imports successfully, exposes `app` and a compiled `agent`, and **every key of the shipped `config/config.yaml` reaches `agent.config`** — so no runtime parameter is inert on the standalone path while still applying on the AgentRegistry path. |


## Test Execution Summary

> Acceptance evidence for this template = a green `run-tests` + `gate-stub-check` plus the TC / PB / BL
> matrices above, each traced to a real test function. Concrete pass / skip counts are transcribed
> **verbatim from this MR's green `run-tests` trace once it completes** — they are not asserted here
> before the run (Stage ④ spec is written before this MR's own pipeline runs). The compiled-graph
> `agent.invoke()` E2E runs against the real framework in CI and `importorskip`s where that runtime is
> absent. Coverage is reported by `run-tests` under an advisory threshold (see Test Strategy →
> Coverage); the concrete coverage figure, like the pass / skip counts, is read from this MR's green
> pipeline evidence rather than asserted here before the run.
