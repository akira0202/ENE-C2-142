# ENE-C2-142 — Unit tests: worksheet-directed value extraction service (framework-free).
#
# Covers conformant / missing / ambiguous references, verbatim rule recording, value taken as-is
# (no transform / no candidate choice), provenance carried onto conformant entries, the
# resolution -> extraction contract (resolve() output feeds extract_values()), and structural
# fail-closed input errors.
# Framework-free, so it runs locally and in CI.

import pytest

from src.services.value_extraction import ERR_EXTRACT_INPUT, ExtractionError, extract_values


def _resolved(geography="shibata-city", unit="GWh", value=1.5, source_version="2025.1"):
    return {
        "geography": geography,
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": unit,
        "value": value,
        "source_version": source_version,
        "dataset_id": "jed",
        "dataset_version": "2025.1",
    }


def _directive(geography="shibata-city", unit="GWh", rule="latest approved"):
    return {
        "geography": geography,
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": unit,
        "value_selection_rule": rule,
    }


def _assert_input_error(resolved, worksheet):
    with pytest.raises(ExtractionError) as exc:
        extract_values(resolved, worksheet)
    assert exc.value.code == ERR_EXTRACT_INPUT


# --- conformant ---------------------------------------------------------------------------
def test_conformant_takes_supplied_value_as_is():
    out = extract_values([_resolved(value=42.0)], [_directive()])
    assert len(out) == 1
    e = out[0]
    assert e["extraction_status"] == "conformant"
    assert e["value"] == 42.0  # supplied value, unchanged
    assert e["candidate_count"] == 1
    assert e["value_selection_rule"] == "latest approved"  # recorded verbatim
    assert e["provenance"]["source_version"] == "2025.1"
    assert e["provenance"]["dataset_id"] == "jed"


def test_multiple_directives_each_resolved():
    resolved = [_resolved(unit="GWh", value=1.0), _resolved(unit="TJ", value=2.0)]
    out = extract_values(resolved, [_directive(unit="GWh"), _directive(unit="TJ")])
    assert [e["value"] for e in out] == [1.0, 2.0]


# --- missing ------------------------------------------------------------------------------
def test_missing_reference_flagged_no_value():
    out = extract_values([_resolved(geography="shibata-city")], [_directive(geography="other-city")])
    e = out[0]
    assert e["extraction_status"] == "missing"
    assert e["value"] is None
    assert e["candidate_count"] == 0
    assert e["provenance"] == {}
    assert e["value_selection_rule"] == "latest approved"  # rule still recorded


def test_unit_mismatch_is_missing_never_converted():
    # requested GWh, only TJ available -> missing (never unit-converted)
    out = extract_values([_resolved(unit="TJ", value=3.6)], [_directive(unit="GWh")])
    assert out[0]["extraction_status"] == "missing"
    assert out[0]["value"] is None


# --- ambiguous ----------------------------------------------------------------------------
def test_ambiguous_reference_chooses_nothing():
    # two rows match the same directive -> ambiguous, no candidate chosen even with a rule present
    resolved = [_resolved(value=1.0), _resolved(value=2.0)]
    out = extract_values(resolved, [_directive(rule="priority: latest")])
    e = out[0]
    assert e["extraction_status"] == "ambiguous"
    assert e["value"] is None
    assert e["candidate_count"] == 2
    assert e["provenance"] == {}


# --- resolution -> extraction contract ----------------------------------------------------
def test_consumes_resolution_output():
    from src.services.manifest_resolution import resolve

    workflow_input = {
        "municipality": "Shibata City",
        "jed_extract": [
            {
                "geography": "shibata-city",
                "time_coverage": "2030-annual",
                "energy_type": "electricity",
                "unit": "GWh",
                "value": 1.5,
                "source_version": "2025.1",
                "dataset_id": "jed",
            }
        ],
        "version_manifest": {"dataset_id": "jed", "dataset_version": "2025.1", "coverage": {}},
        "worksheet": [_directive()],
    }
    resolved_rows = resolve(workflow_input)
    out = extract_values(resolved_rows, workflow_input["worksheet"])
    assert out[0]["extraction_status"] == "conformant"
    assert out[0]["value"] == 1.5
    assert out[0]["provenance"]["dataset_version"] == "2025.1"


# --- structural fail-closed ---------------------------------------------------------------
def test_empty_resolved_rows_fails_closed():
    _assert_input_error([], [_directive()])


def test_empty_worksheet_fails_closed():
    _assert_input_error([_resolved()], [])


def test_non_list_inputs_fail_closed():
    _assert_input_error("nope", [_directive()])
    _assert_input_error([_resolved()], "nope")


def test_malformed_directive_fails_closed():
    bad = _directive()
    del bad["value_selection_rule"]
    _assert_input_error([_resolved()], [bad])

    bad2 = _directive()
    del bad2["unit"]
    _assert_input_error([_resolved()], [bad2])
