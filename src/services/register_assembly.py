"""AgentCore Platform v1.0 — scenario-input register assembly for ENE-C2-142 (Step 5).

Deterministic, side-effect-free, framework-free. Serializes the mapped register entries into the
human-review scenario-input register, per docs/02 and the assembly issue:
 - each entry carries the seven mandatory fields (geography, time_coverage, energy_type, unit,
   source_version, value_selection_rule, missing_or_ambiguous) plus the value and allowed optional
   provenance metadata;
 - the missing/ambiguous status and reason are CONSUMED from the mapping step and never re-evaluated,
   inferred, or decided here;
 - a structural input problem fails closed (ERR_ASSEMBLY_INPUT) with no partial register.

Scope boundary: this only serializes the register. Output safety (S-3), name masking, and the
advisory/read-only prohibition scan are the output gate's job; no data-quality/comparability/scenario
decision is made here.
"""

from typing import Any

# Fail-closed error code — non-sensitive, for structural input problems only.
ERR_ASSEMBLY_INPUT = "ERR_ASSEMBLY_INPUT"

# The seven mandatory register fields (docs/02 v1 Source of Truth).
SEVEN_FIELDS = (
    "geography",
    "time_coverage",
    "energy_type",
    "unit",
    "source_version",
    "value_selection_rule",
    "missing_or_ambiguous",
)
# Keys every mapped entry must supply (seven fields + value + provenance metadata from mapping).
_REQUIRED_ENTRY_KEYS = SEVEN_FIELDS + ("value", "provenance", "source_id")


class AssemblyError(Exception):
    """Raised on a structural assembly-input problem. Carries a non-sensitive error CODE."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def assemble_register(register_entries: Any) -> dict[str, Any]:
    """Assemble the human-review scenario-input register from the mapped entries.

    Consumes the mapping step's missing_or_ambiguous status verbatim (never re-evaluated). Returns a
    register dict with the serialized entries and non-decisional summary counts. Raises AssemblyError
    on a structural input problem — a partial register is never returned.
    """
    if not isinstance(register_entries, list) or not register_entries:
        raise AssemblyError(ERR_ASSEMBLY_INPUT)

    rows: list[dict[str, Any]] = []
    flagged = 0
    for entry in register_entries:
        if not isinstance(entry, dict) or any(k not in entry for k in _REQUIRED_ENTRY_KEYS):
            raise AssemblyError(ERR_ASSEMBLY_INPUT)

        row = {field: entry[field] for field in SEVEN_FIELDS}
        row["value"] = entry["value"]
        # Allowed optional provenance metadata (source identifier + resolved provenance references).
        row["source_id"] = entry["source_id"]
        if entry["provenance"]:
            row["provenance"] = entry["provenance"]
        if entry["missing_or_ambiguous"] is not None:
            flagged += 1
        rows.append(row)

    return {"entries": rows, "entry_count": len(rows), "flagged_count": flagged}


def _nonneg_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_valid_register(result: Any) -> bool:
    """A well-formed, self-consistent assembled register. Every invariant is checked in one place so
    a broken projection / wiring cannot release an inconsistent register at the output boundary:
      - result is a dict; entries is a non-empty list;
      - every entry is a dict carrying the seven mandatory fields and a value;
      - each entry is value/flag consistent: a flagged entry (missing_or_ambiguous set) carries no
        value, a conformant entry (missing_or_ambiguous is None) carries one;
      - entry_count / flagged_count are non-bool non-negative ints;
      - entry_count == len(entries); flagged_count == the actual number of flagged entries.
    Framework-free so the full invariant set is exercised in local unit tests."""
    if not isinstance(result, dict):
        return False
    entries = result.get("entries")
    if not isinstance(entries, list) or not entries:
        return False
    entry_count = result.get("entry_count")
    flagged_count = result.get("flagged_count")
    if not _nonneg_int(entry_count) or not _nonneg_int(flagged_count):
        return False
    if entry_count != len(entries):
        return False

    actual_flagged = 0
    for row in entries:
        if not isinstance(row, dict) or any(f not in row for f in SEVEN_FIELDS) or "value" not in row:
            return False
        flagged = row["missing_or_ambiguous"] is not None
        # value/flag consistency: exactly one of "is flagged" / "has a value" must hold.
        if flagged == (row["value"] is not None):
            return False
        actual_flagged += flagged

    return actual_flagged == flagged_count
