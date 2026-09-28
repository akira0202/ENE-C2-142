"""AgentCore Platform v1.0 — input-contract validation for ENE-C2-142 InputIntakeNode.

Deterministic, side-effect-free, framework-free (no agenticstar / framework imports, no I/O).
Validates the three-input v1 contract per docs/02 (v1 Source of Truth) and returns a CANONICAL,
JSON/msgpack-safe validated_input. Every object is rebuilt from an allowlist of known keys — unknown
keys are rejected, not carried through — so no unvalidated nested blob reaches State or the inner
graph. Fails closed with a non-sensitive error CODE (never payload content).

Scope boundary (docs/02 / issue split): this module validates STRUCTURE, FORMAT, one-municipality,
and safe canonical normalization only. It does NOT decide dataset/version or manifest-to-extract
cross-reference consistency — that deterministic resolution belongs exclusively to the resolution
node (Step 2). The manifest's version descriptors are checked for presence/type here, never matched
against the extract.
"""

import csv
import io
import math
from typing import Any

# Fail-closed error codes — non-sensitive, safe for error_log.
# The outer pre_process hands the inner graph a canonical, already-validated payload. A payload
# that fails this validator on the inner side is therefore a broken handoff — this agent's own
# defect — and carries its own code so it is never reported as a request the caller can correct.
ERR_INTERNAL_HANDOFF = "ERR_INTERNAL_HANDOFF"
ERR_SCHEMA = "ERR_SCHEMA"  # malformed / wrong type / bad row structure / unknown key
ERR_MISSING_INPUT = "ERR_MISSING_INPUT"  # a required top-level input is absent
ERR_MUNICIPALITY = "ERR_MUNICIPALITY"  # not exactly one municipality per invocation

# Top-level required inputs (docs/02 v1 Source of Truth).
_REQUIRED_TOP = ("municipality", "jed_extract", "version_manifest", "worksheet")

# Exact column/key allowlists — each row/object is rebuilt from exactly these keys.
_EXTRACT_KEYS = ("geography", "time_coverage", "energy_type", "unit", "value", "source_version", "dataset_id")
_WORKSHEET_KEYS = ("geography", "time_coverage", "energy_type", "unit", "value_selection_rule")
# Manifest: required version descriptors plus optional provenance the resolution node preserves
# when supplied (immutable identifier/URL, checksum). Unknown keys are still rejected.
_MANIFEST_REQUIRED = ("dataset_id", "dataset_version", "coverage")
_MANIFEST_OPTIONAL = ("immutable_ref", "checksum")

# Defensive structural bounds (counts / lengths — not semantic).
_MAX_ROWS = 100_000
_MAX_STR_LEN = 20_000
_MAX_ABS_INT = 2**63  # msgpack int64 bound; larger ints are not checkpoint-safe.
_MAX_DEPTH = 8  # max nesting depth for a free-form JSON value (e.g. manifest coverage)
_MAX_CONTAINER_ITEMS = 1_000  # max items per nested container
_MAX_INPUT_CHARS = 8_000_000  # defensive raw-payload size limit (structural S-2 screen)


def structural_screen(raw: Any) -> str | None:
    """S-2 structural screen of the raw user_input string (runs before parsing). Returns a
    non-sensitive error CODE when the raw payload is unsafe/oversized, else None. Never raises,
    never echoes content. Semantic/PII screening is the framework's baseline input gate; credential
    egress is the terminal output gate — this is structural only (binary/NUL/control/size)."""
    if not isinstance(raw, str):
        return ERR_SCHEMA
    if "\x00" in raw:
        return ERR_SCHEMA
    if len(raw) > _MAX_INPUT_CHARS:
        return ERR_SCHEMA
    control = sum(1 for ch in raw if ord(ch) < 32 and ch not in "\t\n\r")
    if control and control > max(8, len(raw) // 100):
        return ERR_SCHEMA
    return None


class InputContractError(Exception):
    """Raised on any input-contract violation. Carries a non-sensitive error CODE."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _finite_number(value: Any) -> bool:
    """A checkpoint-safe JSON number: a bounded int or a finite float. bool is not a number."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) < _MAX_ABS_INT
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _clean_str(value: Any) -> str:
    """Canonicalize a required string cell: a bounded, non-empty string after trimming, with no
    NUL / C0 control characters (tab / newline / carriage-return excluded — legitimate in free text)."""
    if not isinstance(value, str):
        raise InputContractError(ERR_SCHEMA)
    if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
        raise InputContractError(ERR_SCHEMA)
    text = value.strip()
    if not text or len(text) > _MAX_STR_LEN:
        raise InputContractError(ERR_SCHEMA)
    return text


def _json_safe(value: Any, depth: int = 0) -> Any:
    """Validate and rebuild a free-form JSON value (e.g. the manifest coverage) into a canonical,
    JSON/msgpack-safe, bounded structure. Only None / bool / finite number / bounded control-free
    string / list / dict are allowed; NaN/Infinity, over-deep nesting, over-large containers, and
    non-JSON objects fail closed with ERR_SCHEMA. Nothing is passed through unvalidated."""
    if depth > _MAX_DEPTH:
        raise InputContractError(ERR_SCHEMA)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if not _finite_number(value):
            raise InputContractError(ERR_SCHEMA)
        return value
    if isinstance(value, str):
        if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value) or len(value) > _MAX_STR_LEN:
            raise InputContractError(ERR_SCHEMA)
        return value
    if isinstance(value, list):
        if len(value) > _MAX_CONTAINER_ITEMS:
            raise InputContractError(ERR_SCHEMA)
        return [_json_safe(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > _MAX_CONTAINER_ITEMS:
            raise InputContractError(ERR_SCHEMA)
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > _MAX_STR_LEN:
                raise InputContractError(ERR_SCHEMA)
            if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in key):
                raise InputContractError(ERR_SCHEMA)
            out[key] = _json_safe(item, depth + 1)
        return out
    raise InputContractError(ERR_SCHEMA)


def _rows_from(raw: Any) -> list[dict[str, Any]]:
    """Accept a v1 tabular input as either a JSON array of row-objects or a CSV string; return
    a list of plain dicts. Format/structure errors fail closed with ERR_SCHEMA."""
    if isinstance(raw, str):
        try:
            reader = csv.DictReader(io.StringIO(raw))
            rows = [dict(r) for r in reader]
        except (csv.Error, ValueError):
            raise InputContractError(ERR_SCHEMA)
    elif isinstance(raw, list):
        rows = raw
    else:
        raise InputContractError(ERR_SCHEMA)

    if not rows or len(rows) > _MAX_ROWS:
        raise InputContractError(ERR_SCHEMA)
    for row in rows:
        if not isinstance(row, dict):
            raise InputContractError(ERR_SCHEMA)
    return rows


def _rebuild_row(row: dict[str, Any], keys: tuple[str, ...], *, number_key: str | None = None) -> dict[str, Any]:
    """Rebuild a row from exactly `keys`. Unknown keys are rejected (no blob passthrough).
    `number_key`, when given, must be a finite number; all other cells are required strings."""
    if set(row) != set(keys):
        raise InputContractError(ERR_SCHEMA)
    out: dict[str, Any] = {}
    for key in keys:
        if key == number_key:
            value = row[key]
            # CSV cells arrive as strings — coerce a numeric string, else keep the JSON number.
            if isinstance(value, str):
                try:
                    value = float(value) if ("." in value or "e" in value.lower()) else int(value)
                except ValueError:
                    raise InputContractError(ERR_SCHEMA)
            if not _finite_number(value):
                raise InputContractError(ERR_SCHEMA)
            out[key] = value
        else:
            out[key] = _clean_str(row[key])
    return out


def _normalize_manifest(raw: Any) -> dict[str, Any]:
    """Validate the version manifest is a well-formed JSON object with the version descriptors
    present (structural only — NOT matched against the extract; that is the resolution node's job)."""
    if not isinstance(raw, dict):
        raise InputContractError(ERR_SCHEMA)
    keys = set(raw)
    if not set(_MANIFEST_REQUIRED) <= keys:
        raise InputContractError(ERR_SCHEMA)  # a required descriptor is missing
    if keys - set(_MANIFEST_REQUIRED) - set(_MANIFEST_OPTIONAL):
        raise InputContractError(ERR_SCHEMA)  # unknown manifest key — no blob passthrough
    coverage = raw["coverage"]
    if not isinstance(coverage, (dict, list)):
        raise InputContractError(ERR_SCHEMA)
    out = {
        "dataset_id": _clean_str(raw["dataset_id"]),
        "dataset_version": _clean_str(raw["dataset_version"]),
        # Rebuild coverage into a canonical JSON/msgpack-safe, bounded structure — never a
        # passed-through blob (rejects NaN/Infinity, over-deep/large, control-char strings).
        "coverage": _json_safe(coverage),
    }
    # Optional provenance — preserved when supplied (resolution node stamps it onto resolved rows).
    for key in _MANIFEST_OPTIONAL:
        if key in raw:
            out[key] = _clean_str(raw[key])
    return out


def validate_and_normalize(payload: Any) -> dict[str, Any]:
    """Validate the three-input v1 payload and return a canonical, JSON/msgpack-safe validated_input.

    Enforces: all three required inputs present, exactly one municipality, v1 formats (extract /
    worksheet as JSON array or CSV; manifest as a JSON object), structural/schema validity, and
    safe canonical normalization. Does NOT resolve dataset/version or match manifest to extract.
    Raises InputContractError(code) on any violation; never echoes payload content.
    """
    if not isinstance(payload, dict):
        raise InputContractError(ERR_SCHEMA)

    for key in _REQUIRED_TOP:
        if key not in payload:
            raise InputContractError(ERR_MISSING_INPUT)
    # Reject unknown top-level keys — the same allowlist discipline applied to every row/object,
    # so no extra input rides through silently.
    if set(payload) - set(_REQUIRED_TOP):
        raise InputContractError(ERR_SCHEMA)

    # One municipality per invocation.
    municipality = payload["municipality"]
    if not isinstance(municipality, str) or not municipality.strip():
        raise InputContractError(ERR_MUNICIPALITY)

    extract = [_rebuild_row(r, _EXTRACT_KEYS, number_key="value") for r in _rows_from(payload["jed_extract"])]
    worksheet = [_rebuild_row(r, _WORKSHEET_KEYS) for r in _rows_from(payload["worksheet"])]
    manifest = _normalize_manifest(payload["version_manifest"])

    return {
        "municipality": municipality.strip(),
        "jed_extract": extract,
        "version_manifest": manifest,
        "worksheet": worksheet,
    }
