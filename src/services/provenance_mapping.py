"""AgentCore Platform v1.0 — provenance and unit/coverage mapping for ENE-C2-142 (Step 4).

Deterministic, side-effect-free, framework-free. Maps each worksheet-directed extracted value to its
provenance (source version, source identifier) and resolves its unit/time-coverage status, per
docs/02 and the mapping issue:
 - conformant entries carry their value and the resolved-row provenance;
 - missing / ambiguous / unit-mismatch / coverage-gap entries carry NO value and a design-defined
   status/reason code; unknown units or absent conversion rules are flagged, NEVER converted;
 - fail-closed (ERR_MAPPING_INPUT) is reserved for structural input problems only.

Scope boundary: this only maps provenance/coverage and attaches status codes. It does NOT serialize
the final register or make data-quality / comparability / scenario decisions — final register
assembly belongs exclusively to the assembly node.
"""

from typing import Any

# Fail-closed error code — non-sensitive, for structural input problems only.
ERR_MAPPING_INPUT = "ERR_MAPPING_INPUT"

# Design-defined status/reason codes for the register's missing_or_ambiguous flag.
REASON_ABSENT = "value_absent"  # no row for the requested key at all
REASON_AMBIGUOUS = "multiple_candidates"  # more than one candidate; none chosen
REASON_COVERAGE_GAP = "coverage_gap"  # same geography/energy_type, different time_coverage
REASON_UNRESOLVABLE_UNIT = "unresolvable_unit"  # same geography/time/energy, different unit — never converted

_ENTRY_KEYS = (
    "geography",
    "time_coverage",
    "energy_type",
    "unit",
    "value_selection_rule",
    "extraction_status",
    "candidate_count",
)
_ALLOWED_STATUS = frozenset({"conformant", "missing", "ambiguous"})


class MappingError(Exception):
    """Raised on a structural mapping-input problem. Carries a non-sensitive error CODE."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _missing_reason(entry: dict[str, Any], resolved_rows: list[dict[str, Any]]) -> str:
    """Classify a missing reference by inspecting the resolved rows — unit mismatch and coverage
    gap are distinguished from an outright absent value, and are flagged (never converted)."""
    geo, tc, et, unit = entry["geography"], entry["time_coverage"], entry["energy_type"], entry["unit"]
    same_geo_time_energy = [
        r
        for r in resolved_rows
        if isinstance(r, dict)
        and r.get("geography") == geo
        and r.get("time_coverage") == tc
        and r.get("energy_type") == et
    ]
    if any(r.get("unit") != unit for r in same_geo_time_energy):
        return REASON_UNRESOLVABLE_UNIT
    same_geo_energy = [
        r for r in resolved_rows if isinstance(r, dict) and r.get("geography") == geo and r.get("energy_type") == et
    ]
    if any(r.get("time_coverage") != tc for r in same_geo_energy):
        return REASON_COVERAGE_GAP
    return REASON_ABSENT


def map_provenance_coverage(extracted_values: Any, resolved_rows: Any) -> list[dict[str, Any]]:
    """Map extracted values to provenance + unit/coverage status and return register entries.

    Each entry keeps its geography/time_coverage/energy_type/unit and recorded value_selection_rule.
    Conformant entries carry the supplied value, its source_version and full provenance. Missing,
    ambiguous, unit-mismatch, and coverage-gap entries carry no value and a status/reason code.
    Raises MappingError only on a structural input problem.
    """
    if not isinstance(extracted_values, list) or not extracted_values:
        raise MappingError(ERR_MAPPING_INPUT)
    if not isinstance(resolved_rows, list):
        raise MappingError(ERR_MAPPING_INPUT)

    register_entries: list[dict[str, Any]] = []
    for entry in extracted_values:
        if not isinstance(entry, dict) or any(k not in entry for k in _ENTRY_KEYS):
            raise MappingError(ERR_MAPPING_INPUT)

        mapped: dict[str, Any] = {
            "geography": entry["geography"],
            "time_coverage": entry["time_coverage"],
            "energy_type": entry["energy_type"],
            "unit": entry["unit"],
            "value_selection_rule": entry["value_selection_rule"],
        }

        # A broken upstream contract must fail closed — never be silently mapped to a data flag.
        status = entry["extraction_status"]
        if status not in _ALLOWED_STATUS:
            raise MappingError(ERR_MAPPING_INPUT)
        candidate_count = entry["candidate_count"]

        if status == "conformant":
            provenance = entry.get("provenance")
            if entry.get("value") is None or not isinstance(provenance, dict) or not provenance or candidate_count != 1:
                raise MappingError(ERR_MAPPING_INPUT)
            mapped["value"] = entry["value"]
            mapped["source_version"] = provenance.get("source_version")
            mapped["source_id"] = provenance.get("dataset_id")
            mapped["provenance"] = provenance
            mapped["missing_or_ambiguous"] = None
        else:
            if status == "ambiguous":
                if candidate_count <= 1:
                    raise MappingError(ERR_MAPPING_INPUT)
                reason = REASON_AMBIGUOUS
            else:  # "missing" — refine into unit-mismatch / coverage-gap / absent
                if candidate_count != 0:
                    raise MappingError(ERR_MAPPING_INPUT)
                reason = _missing_reason(entry, resolved_rows)
            mapped["value"] = None
            mapped["source_version"] = None
            mapped["source_id"] = None
            mapped["provenance"] = {}
            mapped["missing_or_ambiguous"] = reason

        register_entries.append(mapped)

    return register_entries
