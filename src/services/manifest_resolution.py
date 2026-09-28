"""AgentCore Platform v1.0 — manifest↔extract resolution for ENE-C2-142 (Step 2).

Deterministic, side-effect-free, framework-free. Resolves the approved caller-supplied JED extract
against the version manifest per docs/02:
 - exact `dataset_id` / `dataset_version` match with manifest↔extract cross-reference consistency;
 - fail closed on any version that is missing / unknown / superseded / schema-mismatched — no
   fallback to an older version and no implicit adaptation;
 - preserve the source version and the available provenance (dataset identity, and the manifest's
   immutable identifier/URL and checksum when supplied) onto each resolved row.

Scope boundary: this owns manifest↔extract resolution ONLY. Input presence/format validation is the
intake node's job; worksheet-directed value extraction is the next node's job. No external retrieval,
refresh, or inference is performed — the manifest is the sole source of approved truth.
"""

from typing import Any

# Fail-closed error codes — non-sensitive, safe for error_log.
ERR_MANIFEST_SCHEMA = "ERR_MANIFEST_SCHEMA"  # manifest metadata missing / malformed
ERR_VERSION_MISMATCH = "ERR_VERSION_MISMATCH"  # an extract row's source_version is not the approved one
ERR_DATASET_MISMATCH = "ERR_DATASET_MISMATCH"  # an extract row's dataset_id is not the manifest's dataset

# Provenance keys the manifest may carry (see input_schema._MANIFEST_OPTIONAL).
_PROVENANCE_KEYS = ("immutable_ref", "checksum")


class ResolutionError(Exception):
    """Raised on any resolution violation. Carries a non-sensitive error CODE."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def resolve(workflow_input: Any) -> list[dict[str, Any]]:
    """Resolve the extract against the manifest and return provenance-stamped resolved rows.

    Cross-reference consistency SSOT: every extract row must carry the same dataset_id as the
    manifest AND a source_version equal to the manifest's approved dataset_version (the canonical
    source-version representation is the version string itself — no prefix-stripping, partial match,
    or fallback). Any missing/unknown/superseded/mismatched dataset or version fails closed
    (ResolutionError) with no fallback — a partial resolution is never returned.
    """
    if not isinstance(workflow_input, dict):
        raise ResolutionError(ERR_MANIFEST_SCHEMA)

    manifest = workflow_input.get("version_manifest")
    extract = workflow_input.get("jed_extract")
    if not isinstance(manifest, dict) or not isinstance(extract, list) or not extract:
        raise ResolutionError(ERR_MANIFEST_SCHEMA)

    dataset_id = manifest.get("dataset_id")
    dataset_version = manifest.get("dataset_version")
    if not _nonempty_str(dataset_id) or not _nonempty_str(dataset_version):
        raise ResolutionError(ERR_MANIFEST_SCHEMA)

    provenance = {k: manifest[k] for k in _PROVENANCE_KEYS if _nonempty_str(manifest.get(k))}

    resolved_rows: list[dict[str, Any]] = []
    for row in extract:
        if (
            not isinstance(row, dict)
            or not _nonempty_str(row.get("source_version"))
            or not _nonempty_str(row.get("dataset_id"))
        ):
            raise ResolutionError(ERR_MANIFEST_SCHEMA)
        # Cross-reference the extract row against the manifest: the dataset identity must match, and
        # the source_version must equal the single approved dataset_version. Both are exact — this
        # fails closed on any wrong dataset or any old/unknown/superseded/mismatched version, with no
        # fallback and no adaptation.
        if row["dataset_id"] != dataset_id:
            raise ResolutionError(ERR_DATASET_MISMATCH)
        if row["source_version"] != dataset_version:
            raise ResolutionError(ERR_VERSION_MISMATCH)
        resolved_rows.append({**row, "dataset_version": dataset_version, **provenance})

    return resolved_rows
