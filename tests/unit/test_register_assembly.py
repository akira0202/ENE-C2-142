# ENE-C2-142 — Unit tests: scenario-input register assembly service (framework-free).
#
# Covers the seven-field output shape + provenance, verbatim consumption of the mapping status
# (no re-evaluation), the mapping -> assembly contract, and structural fail-closed inputs.

import pytest

from src.services.register_assembly import (
    ERR_ASSEMBLY_INPUT,
    AssemblyError,
    assemble_register,
    is_valid_register,
)

_SEVEN = ("geography", "time_coverage", "energy_type", "unit", "source_version",
          "value_selection_rule", "missing_or_ambiguous")


def _entry(reason=None, value=1.5):
    ok = reason is None
    return {
        "geography": "shibata-city",
        "time_coverage": "2030-annual",
        "energy_type": "electricity",
        "unit": "GWh",
        "source_version": "2025.1" if ok else None,
        "value_selection_rule": "latest approved",
        "missing_or_ambiguous": reason,
        "value": value if ok else None,
        "source_id": "jed" if ok else None,
        "provenance": {"dataset_id": "jed", "dataset_version": "2025.1", "source_version": "2025.1"} if ok else {},
    }


def _assert_input_error(entries):
    with pytest.raises(AssemblyError) as exc:
        assemble_register(entries)
    assert exc.value.code == ERR_ASSEMBLY_INPUT


def test_conformant_entry_serializes_seven_fields_and_provenance():
    reg = assemble_register([_entry(value=7.0)])
    assert reg["entry_count"] == 1
    assert reg["flagged_count"] == 0
    row = reg["entries"][0]
    for f in _SEVEN:
        assert f in row
    assert row["value"] == 7.0
    assert row["source_id"] == "jed"
    assert row["provenance"]["dataset_version"] == "2025.1"
    assert row["missing_or_ambiguous"] is None


def test_flag_status_consumed_verbatim_not_re_evaluated():
    reg = assemble_register([_entry(reason="value_absent")])
    row = reg["entries"][0]
    assert row["missing_or_ambiguous"] == "value_absent"  # consumed as-is
    assert row["value"] is None
    assert reg["flagged_count"] == 1
    assert "provenance" not in row  # no provenance for a flagged (no-value) entry


def test_mixed_entries_count_flags():
    reg = assemble_register([_entry(), _entry(reason="multiple_candidates"), _entry(reason="unresolvable_unit")])
    assert reg["entry_count"] == 3
    assert reg["flagged_count"] == 2


def test_consumes_mapping_output():
    from src.services.provenance_mapping import map_provenance_coverage

    extracted = [{
        "geography": "shibata-city", "time_coverage": "2030-annual", "energy_type": "electricity",
        "unit": "GWh", "value_selection_rule": "latest approved", "candidate_count": 1,
        "extraction_status": "conformant", "value": 1.5,
        "provenance": {"dataset_id": "jed", "dataset_version": "2025.1", "source_version": "2025.1"},
    }]
    resolved = [{
        "geography": "shibata-city", "time_coverage": "2030-annual", "energy_type": "electricity",
        "unit": "GWh", "value": 1.5, "source_version": "2025.1", "dataset_id": "jed", "dataset_version": "2025.1",
    }]
    register_entries = map_provenance_coverage(extracted, resolved)
    reg = assemble_register(register_entries)
    assert reg["entries"][0]["value"] == 1.5
    assert reg["entries"][0]["missing_or_ambiguous"] is None


def test_empty_or_non_list_fails_closed():
    _assert_input_error([])
    _assert_input_error("nope")


def test_malformed_entry_fails_closed():
    bad = _entry()
    del bad["source_version"]
    _assert_input_error([bad])


# --- is_valid_register: the full output-boundary invariant set (framework-free) -----------
def _valid_register():
    return assemble_register([_entry(), _entry(reason="value_absent")])  # 2 entries, 1 flagged


def test_is_valid_register_accepts_assembled_output():
    assert is_valid_register(_valid_register()) is True
    assert is_valid_register(assemble_register([_entry()])) is True  # all conformant


@pytest.mark.parametrize("mutate", [
    lambda r: "not a dict",
    lambda r: {},
    lambda r: {**r, "entries": "nope"},
    lambda r: {**r, "entries": []},
    lambda r: {**r, "entry_count": "two"},           # non-int
    lambda r: {**r, "entry_count": True},            # bool
    lambda r: {**r, "flagged_count": -1},            # negative
    lambda r: {**r, "entry_count": 3},               # != len(entries)
    lambda r: {**r, "flagged_count": 0},             # under-counts flags (actual is 1)
    lambda r: {**r, "flagged_count": 2},             # over-counts flags
    lambda r: {**r, "entries": [{"geography": "x"}, r["entries"][1]]},  # entry missing fields
    lambda r: _conformant_without_value(r),          # conformant entry with value None
    lambda r: _flagged_with_value(r),                # flagged entry that still has a value
])
def test_is_valid_register_rejects_inconsistent(mutate):
    assert is_valid_register(mutate(_valid_register())) is False


def _conformant_without_value(r):
    entries = [dict(r["entries"][0]), r["entries"][1]]
    entries[0]["value"] = None  # conformant (missing_or_ambiguous None) but no value
    return {**r, "entries": entries}


def _flagged_with_value(r):
    entries = [r["entries"][0], dict(r["entries"][1])]
    entries[1]["value"] = 9.9  # flagged (missing_or_ambiguous set) but carries a value
    return {**r, "entries": entries}
