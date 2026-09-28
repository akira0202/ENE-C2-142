"""AgentCore Platform v1.0 — worksheet-directed value extraction for ENE-C2-142 (Step 3).

Deterministic, side-effect-free, framework-free. Extracts the values the worksheet directives ask
for from the resolved extract rows, per docs/02 and the value-extraction issue:
 - each worksheet directive selects resolved rows by (geography, time_coverage, energy_type, unit);
 - the declared value_selection_rule is recorded verbatim — it is NEVER applied, so the node never
   chooses between candidates, interpolates, infers, or silently transforms a value;
 - exactly one match -> the supplied value is taken as-is (conformant); zero matches -> flagged
   `missing`; more than one match -> flagged `ambiguous` (no value chosen). These are per-entry flags
   in the structured result, not fail-closed errors (fail-closed is reserved for structural input
   problems).

Scope boundary: version resolution is the previous node's job; provenance / unit-coverage mapping
and register assembly are later nodes'. This node only extracts the directed values.
"""

from typing import Any

# Fail-closed error code — non-sensitive, for structural input problems only.
ERR_EXTRACT_INPUT = "ERR_EXTRACT_INPUT"

# The directive dimensions that select a resolved row.
_MATCH_KEYS = ("geography", "time_coverage", "energy_type", "unit")
# Provenance carried from the matched resolved row onto a conformant extracted value.
_PROVENANCE_KEYS = ("dataset_id", "dataset_version", "source_version", "immutable_ref", "checksum")


class ExtractionError(Exception):
    """Raised on a structural extraction-input problem. Carries a non-sensitive error CODE."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _match_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(k) for k in _MATCH_KEYS)


def extract_values(resolved_rows: Any, worksheet: Any) -> list[dict[str, Any]]:
    """Extract worksheet-directed values from the resolved rows.

    Returns one structured entry per worksheet directive, each carrying the recorded
    value_selection_rule and an extraction_status of conformant / missing / ambiguous. The supplied
    value is copied unchanged for a conformant match; missing and ambiguous entries carry no value
    (no candidate is ever chosen). Raises ExtractionError only on a structural input problem.
    """
    if not isinstance(resolved_rows, list) or not resolved_rows:
        raise ExtractionError(ERR_EXTRACT_INPUT)
    if not isinstance(worksheet, list) or not worksheet:
        raise ExtractionError(ERR_EXTRACT_INPUT)

    extracted: list[dict[str, Any]] = []
    for directive in worksheet:
        if not isinstance(directive, dict) or "value_selection_rule" not in directive:
            raise ExtractionError(ERR_EXTRACT_INPUT)
        if any(k not in directive for k in _MATCH_KEYS):
            raise ExtractionError(ERR_EXTRACT_INPUT)

        key = tuple(directive[k] for k in _MATCH_KEYS)
        matches = [r for r in resolved_rows if isinstance(r, dict) and _match_key(r) == key]

        entry: dict[str, Any] = {k: directive[k] for k in _MATCH_KEYS}
        # value_selection_rule is recorded verbatim — never applied to choose a candidate.
        entry["value_selection_rule"] = directive["value_selection_rule"]
        entry["candidate_count"] = len(matches)

        if len(matches) == 1:
            entry["extraction_status"] = "conformant"
            entry["value"] = matches[0].get("value")  # supplied value, taken as-is (no transform)
            entry["provenance"] = {k: matches[0][k] for k in _PROVENANCE_KEYS if k in matches[0]}
        else:
            # zero -> missing; more than one -> ambiguous. No candidate is chosen either way.
            entry["extraction_status"] = "missing" if not matches else "ambiguous"
            entry["value"] = None
            entry["provenance"] = {}

        extracted.append(entry)

    return extracted
