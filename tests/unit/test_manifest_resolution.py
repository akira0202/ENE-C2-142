# ENE-C2-142 — Unit tests: manifest↔extract resolution service (framework-free).
#
# Covers valid resolution + provenance stamping, and the adversarial version paths: mismatched /
# old (no fallback) source_version, and malformed manifest/extract metadata. Framework-free, so it
# runs locally and in CI.

import pytest

from src.services.manifest_resolution import (
    ERR_DATASET_MISMATCH,
    ERR_MANIFEST_SCHEMA,
    ERR_VERSION_MISMATCH,
    ResolutionError,
    resolve,
)


def _row(source_version="2025.1", value=1.5, dataset_id="jed"):
    return {
        "geography": "shibata-city",
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": "GWh",
        "value": value,
        "source_version": source_version,
        "dataset_id": dataset_id,
    }


def _workflow(rows=None, manifest=None):
    return {
        "jed_extract": rows if rows is not None else [_row()],
        "version_manifest": manifest
        if manifest is not None
        else {"dataset_id": "jed", "dataset_version": "2025.1", "coverage": {"years": [2030]}},
    }


def _assert_code(workflow, code):
    with pytest.raises(ResolutionError) as exc:
        resolve(workflow)
    assert exc.value.code == code


# --- valid resolution + provenance --------------------------------------------------------
def test_valid_resolution_stamps_dataset_identity():
    rows = resolve(_workflow())
    assert len(rows) == 1
    assert rows[0]["dataset_id"] == "jed"
    assert rows[0]["dataset_version"] == "2025.1"
    assert rows[0]["source_version"] == "2025.1"
    # original row fields preserved
    assert rows[0]["value"] == 1.5


def test_optional_provenance_preserved_when_supplied():
    manifest = {
        "dataset_id": "jed",
        "dataset_version": "2025.1",
        "coverage": {"years": [2030]},
        "immutable_ref": "https://example.invalid/jed/2025.1",
        "checksum": "sha256:abc",
    }
    rows = resolve(_workflow(manifest=manifest))
    assert rows[0]["immutable_ref"] == "https://example.invalid/jed/2025.1"
    assert rows[0]["checksum"] == "sha256:abc"


def test_absent_provenance_is_simply_not_stamped():
    rows = resolve(_workflow())
    assert "immutable_ref" not in rows[0]
    assert "checksum" not in rows[0]


def test_all_matching_rows_resolve():
    rows = resolve(_workflow(rows=[_row(value=1.0), _row(value=2.0)]))
    assert [r["value"] for r in rows] == [1.0, 2.0]


# --- adversarial version paths (fail closed, no fallback) ---------------------------------
def test_version_mismatch_fails_closed():
    _assert_code(_workflow(rows=[_row(source_version="2024.3")]), ERR_VERSION_MISMATCH)


def test_no_fallback_when_any_row_is_old_version():
    # One current + one superseded row: the whole resolution fails closed (no partial, no fallback).
    _assert_code(_workflow(rows=[_row(source_version="2025.1"), _row(source_version="2024.3")]),
                 ERR_VERSION_MISMATCH)


def test_dataset_id_mismatch_fails_closed():
    # A row from a different dataset must not be stamped as the manifest's dataset.
    _assert_code(_workflow(rows=[_row(dataset_id="other-db")]), ERR_DATASET_MISMATCH)


def test_row_missing_dataset_id():
    bad = _row()
    del bad["dataset_id"]
    _assert_code(_workflow(rows=[bad]), ERR_MANIFEST_SCHEMA)


def test_resolves_the_intake_nodes_normalized_output():
    # Contract consistency: a normal validated_input produced by the intake service (#6) must
    # resolve here — the canonical source-version / dataset_id representations agree end to end.
    from src.services.input_schema import validate_and_normalize

    payload = {
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
        "version_manifest": {"dataset_id": "jed", "dataset_version": "2025.1", "coverage": {"years": [2030]}},
        "worksheet": [
            {
                "geography": "shibata-city",
                "time_coverage": "2030-annual",
                "energy_type": "electricity",
                "unit": "GWh",
                "value_selection_rule": "latest approved",
            }
        ],
    }
    validated = validate_and_normalize(payload)
    rows = resolve(validated)
    assert len(rows) == 1
    assert rows[0]["dataset_id"] == "jed"
    assert rows[0]["dataset_version"] == "2025.1"


# --- malformed manifest / extract metadata ------------------------------------------------
def test_non_dict_workflow():
    _assert_code(["not", "a", "dict"], ERR_MANIFEST_SCHEMA)


def test_empty_extract():
    _assert_code(_workflow(rows=[]), ERR_MANIFEST_SCHEMA)


def test_manifest_missing_dataset_version():
    _assert_code(_workflow(manifest={"dataset_id": "jed", "coverage": {}}), ERR_MANIFEST_SCHEMA)


def test_manifest_missing_dataset_id():
    _assert_code(_workflow(manifest={"dataset_version": "2025.1", "coverage": {}}), ERR_MANIFEST_SCHEMA)


def test_row_missing_source_version():
    bad = _row()
    del bad["source_version"]
    _assert_code(_workflow(rows=[bad]), ERR_MANIFEST_SCHEMA)
