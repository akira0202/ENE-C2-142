# ENE-C2-142 — Unit tests: input-contract validation service (framework-free).
#
# Covers the v1 three-input contract (docs/02 v1 Source of Truth): valid pass-through in both
# JSON-array and CSV forms, canonical normalization, and the fail-closed error codes for missing
# inputs, municipality, and structural/schema violations — plus the S-2 structural screen. This
# module imports no framework code, so it runs locally and in CI.

import json

import pytest

from src.services.input_schema import (
    ERR_MISSING_INPUT,
    ERR_MUNICIPALITY,
    ERR_SCHEMA,
    InputContractError,
    structural_screen,
    validate_and_normalize,
)


def _extract_row(value=1.5):
    return {
        "geography": "shibata-city",
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": "GWh",
        "value": value,
        "source_version": "2025.1",  # canonical source-version == manifest dataset_version
        "dataset_id": "jed",         # cross-references manifest dataset_id
    }


def _worksheet_row():
    return {
        "geography": "shibata-city",
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": "GWh",
        "value_selection_rule": "latest approved",
    }


def _manifest():
    return {"dataset_id": "jed", "dataset_version": "2025.1", "coverage": {"years": [2030]}}


def _valid():
    return {
        "municipality": "Shibata City",
        "jed_extract": [_extract_row()],
        "version_manifest": _manifest(),
        "worksheet": [_worksheet_row()],
    }


def _assert_code(payload, code):
    with pytest.raises(InputContractError) as exc:
        validate_and_normalize(payload)
    assert exc.value.code == code


# --- valid --------------------------------------------------------------------------------
def test_valid_json_payload_normalizes():
    out = validate_and_normalize(_valid())
    assert out["municipality"] == "Shibata City"
    assert out["jed_extract"] == [_extract_row()]
    assert out["worksheet"] == [_worksheet_row()]
    assert out["version_manifest"] == _manifest()
    # canonical + JSON/msgpack-safe (round-trips)
    assert json.loads(json.dumps(out)) == out


def test_valid_csv_tabular_form_parses():
    p = _valid()
    p["jed_extract"] = (
        "geography,time_coverage,energy_type,unit,value,source_version,dataset_id\r\n"
        "shibata-city,2030-annual,electricity,GWh,1.5,2025.1,jed\r\n"
    )
    out = validate_and_normalize(p)
    assert out["jed_extract"] == [_extract_row()]  # numeric string coerced to float


def test_whitespace_is_trimmed():
    p = _valid()
    p["jed_extract"][0]["geography"] = "  shibata-city  "
    assert validate_and_normalize(p)["jed_extract"][0]["geography"] == "shibata-city"


# --- missing inputs / municipality --------------------------------------------------------
@pytest.mark.parametrize("key", ["municipality", "jed_extract", "version_manifest", "worksheet"])
def test_missing_required_input(key):
    p = _valid()
    del p[key]
    _assert_code(p, ERR_MISSING_INPUT)


@pytest.mark.parametrize("bad", ["", "   ", 123, None, ["a", "b"]])
def test_municipality_must_be_one_nonempty_string(bad):
    p = _valid()
    p["municipality"] = bad
    _assert_code(p, ERR_MUNICIPALITY)


# --- structural / schema violations -------------------------------------------------------
def test_payload_not_object():
    _assert_code(["not", "an", "object"], ERR_SCHEMA)


def test_empty_extract_rejected():
    p = _valid()
    p["jed_extract"] = []
    _assert_code(p, ERR_SCHEMA)


def test_extract_missing_column():
    p = _valid()
    del p["jed_extract"][0]["unit"]
    _assert_code(p, ERR_SCHEMA)


def test_extract_unknown_column_rejected():
    # No unvalidated blob may ride through — unknown keys are rejected, not carried.
    p = _valid()
    p["jed_extract"][0]["raw_blob"] = {"x": [1, 2]}
    _assert_code(p, ERR_SCHEMA)


def test_extract_value_must_be_finite_number():
    for bad in ["abc", float("nan"), float("inf"), True, 2 ** 63]:
        p = _valid()
        p["jed_extract"][0]["value"] = bad
        _assert_code(p, ERR_SCHEMA)


def test_worksheet_missing_column():
    p = _valid()
    del p["worksheet"][0]["value_selection_rule"]
    _assert_code(p, ERR_SCHEMA)


def test_manifest_must_be_object_with_version_descriptors():
    p = _valid()
    p["version_manifest"] = ["not", "an", "object"]
    _assert_code(p, ERR_SCHEMA)

    p = _valid()
    del p["version_manifest"]["dataset_version"]
    _assert_code(p, ERR_SCHEMA)


def test_manifest_optional_provenance_accepted():
    p = _valid()
    p["version_manifest"]["immutable_ref"] = "https://example.invalid/jed/2025.1"
    p["version_manifest"]["checksum"] = "sha256:abc"
    out = validate_and_normalize(p)
    assert out["version_manifest"]["immutable_ref"] == "https://example.invalid/jed/2025.1"
    assert out["version_manifest"]["checksum"] == "sha256:abc"


def test_manifest_unknown_key_rejected():
    p = _valid()
    p["version_manifest"]["smuggled"] = {"x": 1}
    _assert_code(p, ERR_SCHEMA)


def test_top_level_unknown_key_rejected():
    # The row/object allowlist discipline applies at the top level too — no extra input rides through.
    p = _valid()
    p["extra_top_level"] = {"smuggled": True}
    _assert_code(p, ERR_SCHEMA)


def test_coverage_is_rebuilt_json_safe_when_valid():
    p = _valid()
    p["version_manifest"]["coverage"] = {"years": [2030, 2035], "geographies": ["shibata-city"]}
    out = validate_and_normalize(p)
    assert out["version_manifest"]["coverage"] == {"years": [2030, 2035], "geographies": ["shibata-city"]}


def test_coverage_rejects_non_finite_number():
    for bad in (float("nan"), float("inf"), -float("inf"), 2 ** 63):
        p = _valid()
        p["version_manifest"]["coverage"] = {"metric": bad}
        _assert_code(p, ERR_SCHEMA)


def test_coverage_rejects_over_deep_nesting():
    node: dict = {}
    cur = node
    for _ in range(12):  # exceeds _MAX_DEPTH
        cur["n"] = {}
        cur = cur["n"]
    p = _valid()
    p["version_manifest"]["coverage"] = node
    _assert_code(p, ERR_SCHEMA)


def test_coverage_rejects_non_json_type():
    p = _valid()
    p["version_manifest"]["coverage"] = {"bad": {1, 2, 3}}  # a set is not JSON/msgpack-safe
    _assert_code(p, ERR_SCHEMA)


def test_coverage_rejects_control_char_string():
    p = _valid()
    p["version_manifest"]["coverage"] = {"label": "cover\x00age"}
    _assert_code(p, ERR_SCHEMA)


def test_control_character_in_cell_rejected():
    # A NUL (or other C0 control) in a string cell survives JSON round-trip and is a classic
    # truncation/injection vector — rejected structurally (tab/newline/CR remain allowed).
    p = _valid()
    p["worksheet"][0]["value_selection_rule"] = "rule\x00smuggled"
    _assert_code(p, ERR_SCHEMA)


# --- S-2 structural screen ----------------------------------------------------------------
def test_structural_screen_accepts_clean_json_string():
    assert structural_screen(json.dumps(_valid())) is None


@pytest.mark.parametrize(
    "raw",
    [
        123,                      # non-str
        "ok\x00nul",             # NUL byte
        "\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c",  # control-char heavy
        "x" * (8_000_001),       # oversized
    ],
)
def test_structural_screen_rejects_unsafe(raw):
    assert structural_screen(raw) == ERR_SCHEMA
