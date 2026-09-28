"""AgentCore Platform v1.0 — caller-facing wording for runs that end without a register.

Each outcome here is reported by completing the run with an allow-listed ``diagnostic_code`` and a
fixed sentence derived from that code alone. No request value, source content or identifier is ever
interpolated, so a notice can never echo caller content back. On such a run ``status=SUCCESS`` means
the agent finished handling the request safely; it does not mean a register was produced.

Caller-correctable (the request does not meet the input contract, or its rows disagree with the
manifest it was sent with): the input-contract codes owned by ``input_schema``, and the two
mismatch codes owned by ``manifest_resolution``. Each sentence names what to send instead. No
register is assembled and no source content is echoed.

Policy withholding on output: ``REGISTER_WITHHELD`` when the assembled register would carry an
operational directive (control, dispatch, trading, tariff, optimization or forecast wording) — this
agent extracts evidence for a human to read, it never tells anyone to act. The register is not
released in part or in full; the matched category is recorded in the audit trail only.

Not reported here, and ending as ``status=ERROR`` instead: input refused by the S-2 structural
screen, credential-shaped content (the framework's baseline S-3 scan), a register whose shape
breaks the output contract, the structural input contracts between the inner nodes, and a broken
handoff between the outer and inner graph. This agent produces those itself, so they are defects
rather than requests to correct, and none is ever represented as a successful completion.
"""

from __future__ import annotations

from src.services.input_schema import ERR_MISSING_INPUT, ERR_MUNICIPALITY, ERR_SCHEMA
from src.services.manifest_resolution import ERR_DATASET_MISMATCH, ERR_VERSION_MISMATCH

REGISTER_WITHHELD = "REGISTER_WITHHELD"

_FOUR_INPUTS = "municipality, jed_extract, version_manifest and worksheet"

# Each notice is released as the output, so each is worded to pass the same output policy a
# register must pass — none of them tells the reader to act.
_MESSAGES: dict[str, str] = {
    ERR_SCHEMA: (
        f"The request does not match the documented shape. Send a JSON object holding {_FOUR_INPUTS}, "
        "with each extract row carrying exactly its documented columns."
    ),
    ERR_MISSING_INPUT: (
        f"The request is missing one of its four required inputs. All of {_FOUR_INPUTS} must be present."
    ),
    ERR_MUNICIPALITY: "The request must name exactly one municipality, as a non-empty string.",
    ERR_VERSION_MISMATCH: (
        "An extract row carries a source_version that differs from the version_manifest's "
        "dataset_version. Send rows drawn from the manifest's own version — this agent never "
        "substitutes another version."
    ),
    ERR_DATASET_MISMATCH: (
        "An extract row carries a dataset_id that differs from the version_manifest's dataset_id. "
        "Send rows from the dataset the manifest describes."
    ),
    REGISTER_WITHHELD: (
        "No register was returned. The assembled register would have gone beyond the evidence this "
        "agent reports, so nothing in it was released. Check the wording of the supplied worksheet "
        "and extract rows."
    ),
}

# Every code this module answers. A node degrades only with one of these; anything else is a defect.
DEGRADATION_CODES = frozenset(_MESSAGES)

_FALLBACK = "The request could not be completed and no register was produced."


def explain_degradation(code: str) -> str:
    """Return one caller-facing sentence for a degradation code."""
    return _MESSAGES.get(code, f"{_FALLBACK} [{code}]" if code else _FALLBACK)
