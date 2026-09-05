from __future__ import annotations

from hl_observer.ops.canonical_775_guard import (
    KNOWN_CANONICAL_ANCHORS,
    ROADMAP_ID,
    ROADMAP_TOTAL,
    _valid_sha256,
    validate_manifest,
)


def _literal_done_manifest() -> dict:
    labels = [f"canonical-label-{number}" for number in range(1, ROADMAP_TOTAL + 1)]
    for number, expected in KNOWN_CANONICAL_ANCHORS.items():
        labels[number - 1] = expected
    proofs = {
        str(number): {"command": f"python -m pytest proof-{number}"}
        for number in range(1, ROADMAP_TOTAL + 1)
    }
    # A non-numeric metadata key must be ignored rather than treated as proof.
    proofs["metadata"] = {"command": "ignored"}
    return {
        "roadmap_id": ROADMAP_ID,
        "total": ROADMAP_TOTAL,
        "legacy_master_v6_equivalent": False,
        "anchors": {str(k): v for k, v in KNOWN_CANONICAL_ANCHORS.items()},
        "status": "DONE",
        "labels": labels,
        "proofs": proofs,
    }


def test_done_accepts_distinct_mapping_proofs_and_ignores_non_numeric_metadata() -> None:
    result = validate_manifest(_literal_done_manifest())
    assert result["ok"] is True
    assert result["issues"] == []


def test_done_rejects_literal_anchor_mismatch_after_full_label_validation() -> None:
    manifest = _literal_done_manifest()
    manifest["labels"][300] = "wrong-anchor"
    result = validate_manifest(manifest)
    assert result["ok"] is False
    assert "DONE_LITERAL_LABEL_MISMATCH:301" in result["issues"]


def test_sha256_validator_rejects_non_hex_digest_of_valid_length() -> None:
    assert _valid_sha256("z" * 64) is False
