# Template Design Specification

> Municipal Energy-Scenario Input Evidence Extractor (Cat 2, ENE).
> Read-only: turns caller-supplied approved Japan Energy Database extracts, a dataset-version
> manifest, and a municipal scenario worksheet into a provenance-rich scenario-input register.
> No inference beyond supplied data; every assumption and downstream decision stays with the
> human scenario owner.

## v1 Source of Truth

**One municipality per invocation.** Three caller-supplied inputs, delivered as a single JSON
`user_input` payload (each document inlined or referenced as parsed content):

| Input | Format | Purpose |
|-------|--------|---------|
| Approved JED extract | CSV or JSON | Approved rows for the municipality: per row `geography`, `time_coverage` (annual or hourly), `energy_type`, `unit`, `value`, a `source_version` reference, and the `dataset_id` the row belongs to (cross-referenced against the manifest at Step 2). "Approved" is **caller-asserted**, not agent-verified. |
| Version manifest | JSON | Declares the dataset version and coverage/provenance of the extract; used to stamp `source_version`. |
| Municipal scenario worksheet | CSV or JSON | Caller directives: which `(geography × time_coverage × energy_type × unit)` entries the scenario needs, and the value-selection rule per entry. |

**Manifest ↔ extract matching.** The extract's declared source version must match and be consistent
with the manifest; a mismatch fails closed with no fallback (provenance cannot be certified). This
resolution is owned **solely by Step 2** (`manifest_extract_resolve`); input intake (Step 1) does not
decide dataset/version or cross-reference consistency.

**Seven mandatory register fields (per register entry):**

| # | Field | Source |
|---|-------|--------|
| 1 | `geography` | as supplied |
| 2 | `time_coverage` | as supplied |
| 3 | `energy_type` | as supplied |
| 4 | `unit` | as supplied |
| 5 | `source_version` | manifest / extract (reproducible reference) |
| 6 | `value_selection_rule` | **recorded verbatim** from the worksheet (recording-only, see below) |
| 7 | `missing_or_ambiguous` | flags: absent value, multiple candidates, coverage gap, or unresolvable unit |

**Selection-rule recording-only boundary.** "Recording-only" means the extractor neither invents,
infers, nor applies a selection rule of its own — it records what the worksheet supplied. It does
**not** exempt the recorded text from the safety gates: `value_selection_rule` is caller free text
and is screened at input (S-2) and at the output gate (S-3) like any other free-text field. **The
safety boundary takes precedence over verbatim recording** (see Free-text safety handling below). If
disambiguation would require a rule the worksheet does not supply, the entry is **flagged**, never
auto-resolved.

**Flag-versus-error decision.** Contract failures fail closed; data gaps within valid inputs are
flagged — surfacing gaps for the human is the deliverable, not a failure.

| Outcome | Condition | Result |
|---------|-----------|--------|
| **Notice** (caller-correctable, no register) | malformed/unparseable input, missing required input, unknown top-level key, worksheet/structural schema violation, or no single municipality (Step 1); extract↔manifest version / dataset mismatch, no fallback (Step 2) | `status = success`, `diagnostic_code` = the code, output = the fixed notice naming what to send instead; the later steps are skipped |
| **Notice** (policy withholding, no register) | domain-prohibited / control-instruction wording in the assembled register (Step 5 output policy) | `status = success`, `diagnostic_code = REGISTER_WITHHELD`, output = the fixed notice; the register is cleared and the matched category is recorded in the audit trail only |
| **Error** (fail-closed, no partial register) | input refused by the S-2 structural screen; credential-shaped content anywhere in output (framework S-3 credential scan); a broken outer→inner handoff (`ERR_INTERNAL_HANDOFF`); the structural input contracts between the inner nodes (manifest / extraction / mapping / assembly); a malformed or inconsistent register at the output gate — this agent produces all of these itself | `status = error`, non-sensitive diagnostic code, no register |
| **Flag** (register produced, entry annotated in field 7) | requested value absent in extract; ambiguous (multiple candidates, no supplied rule); requested period only partially covered; unit present but not resolvable to the requested unit (recorded, never converted) | `status = success`, register with `missing_or_ambiguous` populated |

`status = success` with a `diagnostic_code` means the request was handled safely, not that a
register was produced. Every notice is derived from the allow-listed code alone
(`src/services/degradation.py`) and is worded to pass the same output policy a register must pass,
so no request value or withheld content reaches the caller.

**How the marker crosses the inner boundary.** An inner node that errors is re-raised as
`SubgraphError` *before* `merge_output()` runs, so an inner error can never carry its code outward.
A caller-correctable rejection therefore **completes** the inner graph instead: the node returns
`SUCCESS` + `diagnostic_code`, each inner hop is conditional on that marker as well as on the
status, `get_output()` projects it, and `merge_output()` maps it (the outer marker wins — it names
the specific reason). `main` skips the inner workflow entirely when pre_process already set it.

**Free-text safety handling (precedence over verbatim).** Any caller free-text that is recorded
and/or returned — notably `value_selection_rule`, worksheet notes, manifest descriptions, and source
labels — is treated as untrusted. At input the intake node applies structural screening (non-text /
NUL / control-character / oversized) and the framework baseline S-2 PII scan runs on `user_input`;
credential detection is **not** hand-rolled at input (substrate reuse). On the way out the framework
baseline S-3 credential scan fail-closes the run on any credential-shaped content, and the terminal
output gate masks labelled Japanese personal names with a safe placeholder and blocks
domain-prohibited / control-instruction output (Step 5 output policy; v1 has no LLM sink, so this is
defence-in-depth). `value_selection_rule` is therefore recorded and echoed **verbatim only for
content that passes these safety checks** — the safety boundary always wins. Verification (Stage ④
boundary perspective): no register free-text field, including `value_selection_rule`, leaves the
output gate with an unmasked personal name or credential-shaped content.

**Boundaries.** Read-only (no write-back, no side effects); no inference beyond supplied values
(no interpolation, extrapolation, estimation, or unit conversion); no modeling (no demand forecast,
investment optimization, tariff calculation, dispatch, trading, or grid control); associations are
locational/reference-only, never causal or emission attribution to a specific asset; the register
and its flags are handed off to a human scenario owner who makes every assumption and decision.

## Position in AgentCore Architecture

- **Agent Class**: `MunicipalEnergyScenarioInputEvidenceExtractorGraph`
  (defined in `src/graph/graph.py`, re-exported from `src/graph/__init__.py`)
- **L1 Base**: **AgentBaseGraph** (Cat 2, L1-direct; no Level 2 base-agent inheritance)
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

## Architecture Overview

Cat 2 uses two layers. The **outer graph** is the fixed 5-node `AgentBaseGraph` backbone
(`add_edges()` is **not** overridden). The multi-step domain workflow is encapsulated in an
**inner graph** wrapped by a `GraphNode` in the `main` slot.

### Node Configuration

Outer graph (`MunicipalEnergyScenarioInputEvidenceExtractorGraph(AgentBaseGraph)`) — fixed 5-node backbone:

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | framework default | — | — | InitializeNode (default) |
| pre_process | Step 1 — three-input intake + worksheet normalization; parse `user_input` JSON (reject malformed), enforce the three-input contract, structural/schema validity, and safe canonical normalization; screen untrusted free text. Does **not** decide dataset/version or manifest↔extract matching (owned solely by Step 2) | `user_input` | `validated_input`, `status` | `InputIntakeNode(FunctionNode)` — override `execute()` |
| main | run the domain workflow (Steps 2–5) via the inner graph | `validated_input` | `result`, `status` | `ScenarioExtractWorkflowGraphNode(GraphNode)` — `get_subgraph()`/`extract_input()`/`merge_output()` |
| post_process | output gate — terminal output screening over the assembled register; pass formats it, violation fails closed | `result` | `formatted_output`, `status` | `OutputGateNode(FunctionNode)` — override `execute()` |
| finalize | framework default | — | — | FinalizeNode (default) |

**Inner graph (domain workflow) nodes** (`src/graph/domain_workflow_graph.py`, `…WorkflowGraph(BaseGraph)`; linear; fail-closed short-circuit to END on any node `status = error`; every node a `FunctionNode` subclass):

| Node | Responsibility | Input State | Output State |
|------|---------------|-------------|--------------|
| input_hydrate | re-parse/re-validate the JSON string handed in by the outer GraphNode into the inner working state | `user_input` | `workflow_input` |
| manifest_extract_resolve | Step 2 — sole owner of manifest↔extract resolution: match the extract to the declared manifest version and fail closed on any version/cross-reference mismatch (no fallback); preserve `source_version` and provenance references. Detailed resolution criteria are the resolution node's implementation concern | `workflow_input` | `resolved_rows` |
| worksheet_value_extract | Step 3 — worksheet-directed value extraction; select supplied values per worksheet directives (no inference) | `resolved_rows`, `workflow_input` | `extracted_values` |
| provenance_unit_coverage_map | Step 4 — map provenance and unit/time-coverage per entry; flag missing/ambiguous | `extracted_values` | `register_entries` |
| scenario_register_assemble | Step 5 (assembly) — assemble the seven-field scenario-input register | `register_entries` | `register` |

### GraphNode boundary (outer ↔ inner)

`ScenarioExtractWorkflowGraphNode.extract_input(state)` returns a JSON **string** of `validated_input`,
passed to `inner_graph.invoke(...)`; the inner `input_hydrate` node re-parses it. The inner graph's
`get_output(inner_state)` returns a **narrow dict**
`sub_result = {"register": <seven-field register>, "status": <terminal status>}` — not the inner
working state. `merge_output(state, sub_result)` maps that `sub_result` explicitly:
`sub_result["register"] → result` and `sub_result["status"] → status` (no inner-state projection;
`node_history`/`error_log` are not projected across the boundary). Under `error_strategy = "propagate"`
an inner `status = error` makes the framework raise the subgraph error before `merge_output` runs, so
no partial register crosses the boundary.

### Data Flow

Outer backbone (fixed; `add_edges()` is **not** overridden):

```
START → initialize → pre_process → main → {route} → post_process → finalize → END
                                           ↓ (retry, up to max_retry)
                                        pre_process
```

Inner graph (single linear path; any node `status = error` short-circuits to END, fail closed):

```
START → input_hydrate → manifest_extract_resolve → worksheet_value_extract → provenance_unit_coverage_map → scenario_register_assemble → END
```

### State Definition

The **outer** state adds no domain-specific field; it uses inherited `AgentState` channels only
(`user_input`, `validated_input`, `result`, `formatted_output`, `status`), so nothing is redeclared.
Terminal output is the inherited `result` (framework `get_output()` = `formatted_output or result`);
no custom output field is introduced.

**Inner State** (`…WorkflowState(AgentState)` — domain fields added on top of the inherited channels):

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| workflow_input | dict | hydrated inputs (extract rows, manifest, worksheet directives) parsed from the JSON handoff | yes |
| resolved_rows | list[dict] | extract rows resolved against the manifest, with `source_version` stamped | yes |
| extracted_values | list[dict] | worksheet-directed selected values (as supplied) | yes |
| register_entries | list[dict] | mapped entries with provenance/unit/coverage and missing/ambiguous flags | yes |
| register | dict | the assembled seven-field scenario-input register (surfaced by `get_output()`) | yes |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `InvocationContext.from_state(state)` only (not stored in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (`correlation_id`, `session_id`, `caller_trust_level`, `secrets`) — via `InvocationContext.from_state(state)`
- [ ] ConnectionPolicy (retry/timeout strategy) — not required (no external service call; inputs are caller-supplied)
- [x] SecurityViolationError
- [x] S-2: `_extra_security_gate_input()` — domain-specific input check hook
      (`InputIntakeNode`: structural screening of the untrusted payload — reject non-text / NUL /
      control-character / oversized input, and enforce JSON/msgpack-safe canonical normalization
      with unknown-key rejection. The framework `@final` baseline S-2 PII scan still runs on
      `user_input`; credential-shaped content is caught by the framework S-3 credential scan on
      output — not re-implemented at input (substrate reuse); **MUST NOT override
      `_security_gate_input()`**)
- [x] S-3: `_extra_security_gate_output()` — domain-specific output check hook
      (`OutputGateNode`: the framework output gate scans for credentials only and does **not** mask
      PII; labelled Japanese personal names in any free-text register field (including
      `value_selection_rule`) MUST be masked here on the way out — masking on input alone while
      returning an unmasked name is a leak; any credential-shaped content that reaches output fails
      closed; **MUST NOT override `_security_gate_output()`**)
- [x] S-4: `emit_trace_event()` — at least one domain event inside each `execute()`
      (`inputs_validated`, `extract_resolved`, `values_extracted`, `provenance_mapped`,
      `register_assembled`, `output_gated`; do NOT emit `node_start`/`node_complete`/`node_error`)

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)
> - Custom `BaseNode` subclass → must implement `_security_gate_input()` and
>   `_security_gate_output()` directly (`@abstractmethod` — omission raises `TypeError` at instantiation)

The `main` GraphNode's own S-2/S-3 are deliberate no-ops: the outer `pre_process` bounds the
untrusted input and the outer `post_process` is the terminal output gate, while each inner
`FunctionNode` runs its own gates inside the subgraph.

### Trust boundary (S-1)

- Manifest `required_trust_level`: **VERIFIED_EXTERNAL** — a verified external caller supplying
  approved extracts is a standard business operation. The standalone `/invoke` adapter starts at
  ANONYMOUS and promotes to VERIFIED_EXTERNAL only on a valid bearer token, so this boundary is not
  contradicted by the invoke default.
- Outer boundary FunctionNodes (`InputIntakeNode`, `OutputGateNode`): `TrustLevel.VERIFIED_EXTERNAL`.
- Inner-graph FunctionNodes: `TrustLevel.ANONYMOUS` — S-1 is enforced once at the outer boundary;
  the inner `invoke()` does not re-run the trust gate.
- No authorization decision is derived from `input_context`; no privileged path is gated on a
  caller-supplied claim.

### Runtime configuration

Runtime parameters — `max_retry` and `timeout_seconds` — are not part of the manifest
(`config/agent.yaml` is a static discovery manifest). They live in `config/config.yaml`, which
AgentRegistry loads separately and passes as `Graph(config=...)`; the outer backbone retry loop uses
`max_retry`. This design fixes the intended defaults **`max_retry: 3`, `timeout_seconds: 30`**.
`config/config.yaml` is a runtime artifact, not a Stage ② design deliverable, and is created with
these values at Stage ③ implementation. No runtime value is asserted elsewhere in this document —
this subsection is the single authoritative source.

### Composition Pattern

- **Pattern**: GraphNode (in-process subgraph) in the `main` slot
- **Composition target**: inner `domain_workflow_graph.py` (`BaseGraph`)
- **Error propagation strategy**: **propagate** — inner errors surface as a subgraph error; the
  workflow fails closed with no partial register. `propagate_hitl`: False (non-HITL template).

## EU AI Act Annex III Determination and Art.13 Design-Time Evidence

**Annex III determination: Not in scope.** Annex III §2 (critical infrastructure) covers AI used as
a *safety component in the management or operation* of critical infrastructure such as energy
supply. This template neither manages nor operates energy supply: it is a read-only analyst
input-preparation tool that produces evidence for a human, exercises no control, and makes no
operational decision. The Art.13 transparency evidence below is recorded as design-time evidence.

| Evidence item | Design reference / description |
|---------------|--------------------------------|
| Intended purpose and operating context | Prepare a provenance-rich scenario-input register from caller-supplied approved energy-database extracts, a version manifest, and a municipal scenario worksheet, for municipal energy-planning and utility planning analysts, before a human builds a local energy scenario. |
| System capabilities and limitations | Validates inputs, matches extract to manifest, records worksheet-directed value selections, maps provenance/unit/coverage, and assembles a 7-field register with missing/ambiguous flags. Does not infer, model, forecast, optimize, convert units, or control any system; "approved" is caller-asserted. |
| User-facing transparency information | Every register entry carries a reproducible `source_version`, the recorded `value_selection_rule`, and explicit `missing_or_ambiguous` flags; the output is evidence for human review, not a decision. |
| Human oversight mechanism | The register and its flags are handed off to a human scenario owner; the agent makes no downstream decision and applies no selection rule of its own. |

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: framework/ and shared/ only (no agents/base/ required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | Fixed multi-step workflow (Cat 2), not an autonomous think→act→observe loop. |
| Composition pattern | Standalone backbone | GraphNode + inner graph | **GraphNode + inner graph** | The 5-step domain workflow exceeds the single free `main` slot on the outer backbone; the pipeline lives in an inner `BaseGraph`. |
| `base_type` (manifest metadata) | one of RAGAgent/ChatAgent/ReActAgent/DocGenerationAgent | Other | **Other** | L1-direct on AgentBaseGraph; no Level 2 base-agent is inherited, so no L2 name may be asserted. Value is classification metadata only. |
| `class` (manifest entry point) | bare class name | full dotted import path | **`src.graph.graph.MunicipalEnergyScenarioInputEvidenceExtractorGraph`** | The registry resolves `class` by dotted import; a bare name or nested manifest is not loadable. |
| Trust posture | ANONYMOUS boundary | VERIFIED_EXTERNAL boundary | **VERIFIED_EXTERNAL outer / ANONYMOUS inner** | Verified caller supplying approved extracts; S-1 enforced once at the outer boundary. |
| Error propagation | handle (degrade) | propagate (fail closed) | **propagate** | Provenance integrity requires no partial register on failure. |
| Reporting a run with no register | `status: error` for every rejection | Classify: correctable / withheld → `success` + `diagnostic_code` + fixed notice; security failure / defect → `error` | **Classify** | A caller who can act on the reason gets it as the run's output; the S-2 screen's refusal is not answered with guidance (that would explain how to get past it) and a defect stays visible as a failure to monitoring. |

## Manifest Entry-Point Resolution (`config/agent.yaml`)

The design fixes the manifest architecture values and `config/agent.yaml` is written to the current
registry contract at this stage: **root-level keys** (no `agent:` nesting), **no `module:` key**
(the dotted `class` is the sole entry point), all required root keys present — `id`, `name`,
`namespace`, `version`, `enabled` (bare boolean), `category` (`"Cat 2"`), `industry` (`"ENE"`),
`base_type: "Other"` (L1-direct; no Level 2 base agent), `class`, `required_trust_level` — plus
`requires: { secrets: [], extras: [] }` (LLM-free, no-secret core).

**Entry-point completion condition (Stage ③).** The manifest resolves
`class: "src.graph.graph.MunicipalEnergyScenarioInputEvidenceExtractorGraph"`, but that class is not
implemented or exported yet. The registry resolves the entry point only at discovery/deployment
time; nothing imports it during design. The Stage ③ completion condition is: define
`MunicipalEnergyScenarioInputEvidenceExtractorGraph(AgentBaseGraph)` in `src/graph/graph.py` and
re-export it from `src/graph/__init__.py`, and create `config/config.yaml` with the runtime
parameters (`max_retry: 3`, `timeout_seconds: 30`) per the Runtime configuration subsection above.
Until then no gate imports the class, so the resolved manifest is safe.
