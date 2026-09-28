# ENE-C2-142 — Unit Tests: caller-facing notices for runs that end without a register
# (src/services/degradation.py)
#
# A degraded run completes with one of these notices as its output, so each notice is held to the
# same terminal output policy a register must pass, and none can carry request or source content:
# the sentence is derived from the allow-listed code alone.

import pytest

from src.services import degradation
from src.services.degradation import DEGRADATION_CODES, explain_degradation
from src.services.input_schema import (
    ERR_INTERNAL_HANDOFF,
    ERR_MISSING_INPUT,
    ERR_MUNICIPALITY,
    ERR_SCHEMA,
)
from src.services.manifest_resolution import (
    ERR_DATASET_MISMATCH,
    ERR_MANIFEST_SCHEMA,
    ERR_VERSION_MISMATCH,
)
from src.services.output_policy import scan_prohibited
from src.services.register_assembly import ERR_ASSEMBLY_INPUT


def test_the_codes_a_caller_can_correct_have_a_notice():
    for code in (ERR_SCHEMA, ERR_MISSING_INPUT, ERR_MUNICIPALITY, ERR_VERSION_MISMATCH, ERR_DATASET_MISMATCH):
        assert code in DEGRADATION_CODES


@pytest.mark.parametrize("code", [ERR_INTERNAL_HANDOFF, ERR_MANIFEST_SCHEMA, ERR_ASSEMBLY_INPUT])
def test_a_defect_in_this_agent_is_not_degradable(code):
    # A broken handoff and the structural contracts between the inner nodes are this agent's own
    # doing: they must never be reported as a completed request.
    assert code not in DEGRADATION_CODES


@pytest.mark.parametrize("code", sorted(DEGRADATION_CODES))
def test_every_notice_passes_the_output_policy(code):
    # The notice is released as the output, so it must pass the same gate a register must pass.
    assert scan_prohibited(explain_degradation(code)) is None


@pytest.mark.parametrize("code", sorted(DEGRADATION_CODES))
def test_every_notice_is_its_own_sentence(code):
    notice = explain_degradation(code)
    assert notice and not notice.startswith(degradation._FALLBACK)
    assert code not in notice


def test_an_unknown_code_falls_back_with_its_handle():
    assert explain_degradation("ERR_SOMETHING_ELSE") == f"{degradation._FALLBACK} [ERR_SOMETHING_ELSE]"
    assert explain_degradation("") == degradation._FALLBACK
