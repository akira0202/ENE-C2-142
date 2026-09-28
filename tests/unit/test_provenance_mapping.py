# ENE-C2-142 — Unit tests: provenance and unit/coverage mapping service (framework-free).
#
# Covers conformant mapping (value + provenance), and the design-defined status codes for
# multiple_candidates, value_absent, unresolvable_unit (never converted), and coverage_gap, plus the
# extraction -> mapping contract and structural fail-closed inputs. Runs locally and in CI.

import pytest

from src.services.provenance_mapping import (
    ERR_MAPPING_INPUT,
    REASON_ABSENT,
    REASON_AMBIGUOUS,
    REASON_COVERAGE_GAP,
    REASON_UNRESOLVABLE_UNIT,
    MappingError,
    map_provenance_coverage,
)


def _extracted(status="conformant", unit="GWh", time_coverage="2030-annual", value=1.5):
    entry = {
        "geography": "shibata-city",
        "time_coverage": time_coverage,
        "energy_type": "electricity",
        "unit": unit,
        "value_selection_rule": "latest approved",
        "candidate_count": 1 if status == "conformant" else (2 if status == "ambiguous" else 0),
        "extraction_status": status,
        "value": value if status == "conformant" else None,
        "provenance": {"dataset_id": "jed", "dataset_version": "2025.1", "source_version": "2025.1"}
        if status == "conformant"
        else {},
    }
    return entry


def _resolved(unit="GWh", time_coverage="2030-annual"):
    return {
        "geography": "shibata-city",
        "time_coverage": time_coverage,
        "energy_type": "electricity",
        "unit": unit,
        "value": 1.5,
        "source_version": "2025.1",
        "dataset_id": "jed",
        "dataset_version": "2025.1",
    }


def _assert_input_error(extracted, resolved):
    with pytest.raises(MappingError) as exc:
        map_provenance_coverage(extracted, resolved)
    assert exc.value.code == ERR_MAPPING_INPUT


# --- conformant ---------------------------------------------------------------------------
def test_conformant_maps_value_and_provenance():
    out = map_provenance_coverage([_extracted(value=7.0)], [_resolved()])
    e = out[0]
    assert e["value"] == 7.0
    assert e["source_version"] == "2025.1"
    assert e["source_id"] == "jed"
    assert e["missing_or_ambiguous"] is None
    assert e["value_selection_rule"] == "latest approved"


# --- ambiguous ----------------------------------------------------------------------------
def test_ambiguous_maps_multiple_candidates():
    out = map_provenance_coverage([_extracted(status="ambiguous")], [_resolved()])
    e = out[0]
    assert e["missing_or_ambiguous"] == REASON_AMBIGUOUS
    assert e["value"] is None
    assert e["source_version"] is None


# --- missing -> absent / unit-mismatch / coverage-gap -------------------------------------
def test_missing_absent_when_no_matching_row():
    out = map_provenance_coverage([_extracted(status="missing")], [])
    assert out[0]["missing_or_ambiguous"] == REASON_ABSENT
    assert out[0]["value"] is None


def test_missing_unresolvable_unit_never_converted():
    # requested GWh missing, but a same geo/time/energy row exists in TJ -> unit mismatch, no convert
    out = map_provenance_coverage([_extracted(status="missing", unit="GWh")], [_resolved(unit="TJ")])
    assert out[0]["missing_or_ambiguous"] == REASON_UNRESOLVABLE_UNIT
    assert out[0]["value"] is None


def test_missing_coverage_gap_when_only_other_period_present():
    # requested 2030-annual missing, but same geo/energy exists for a different period -> coverage gap
    out = map_provenance_coverage(
        [_extracted(status="missing", time_coverage="2030-annual")],
        [_resolved(time_coverage="2025-annual")],
    )
    assert out[0]["missing_or_ambiguous"] == REASON_COVERAGE_GAP
    assert out[0]["value"] is None


# --- extraction -> mapping contract -------------------------------------------------------
def test_consumes_extraction_output():
    from src.services.value_extraction import extract_values

    resolved = [_resolved()]
    worksheet = [{
        "geography": "shibata-city",
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": "GWh",
        "value_selection_rule": "latest approved",
    }]
    extracted = extract_values(resolved, worksheet)
    out = map_provenance_coverage(extracted, resolved)
    assert out[0]["missing_or_ambiguous"] is None
    assert out[0]["value"] == 1.5
    assert out[0]["source_version"] == "2025.1"


# --- structural fail-closed ---------------------------------------------------------------
def test_empty_extracted_values_fails_closed():
    _assert_input_error([], [_resolved()])


def test_non_list_inputs_fail_closed():
    _assert_input_error("nope", [_resolved()])
    _assert_input_error([_extracted()], "nope")


def test_malformed_entry_fails_closed():
    bad = _extracted()
    del bad["extraction_status"]
    _assert_input_error([bad], [_resolved()])


def test_unknown_extraction_status_fails_closed():
    # A corrupt upstream status must not be silently treated as a data flag.
    for bad_status in ("typo", None, "", "OK"):
        bad = _extracted()
        bad["extraction_status"] = bad_status
        _assert_input_error([bad], [_resolved()])


def test_status_invariant_violations_fail_closed():
    # conformant without a value / without provenance
    e1 = _extracted(status="conformant")
    e1["value"] = None
    _assert_input_error([e1], [_resolved()])

    e2 = _extracted(status="conformant")
    e2["provenance"] = {}
    _assert_input_error([e2], [_resolved()])

    # conformant with wrong candidate count
    e3 = _extracted(status="conformant")
    e3["candidate_count"] = 2
    _assert_input_error([e3], [_resolved()])

    # missing but candidate_count != 0
    e4 = _extracted(status="missing")
    e4["candidate_count"] = 1
    _assert_input_error([e4], [_resolved()])

    # ambiguous but candidate_count <= 1
    e5 = _extracted(status="ambiguous")
    e5["candidate_count"] = 1
    _assert_input_error([e5], [_resolved()])
