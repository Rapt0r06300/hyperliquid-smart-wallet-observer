from __future__ import annotations

import json

import pytest

from tools.build_copy_vault_external_gap_receipt import (
    SCHEMA,
    build_external_gap_receipt,
)


HEAD = "4fdedb3fdee2f57ceaca6196aa78c0362d2eee68"


def test_gap_is_bound_to_current_head_without_promoting_history() -> None:
    receipt = build_external_gap_receipt(
        task_id="H-T196",
        criterion_id="pr67_reconciled_same_sha",
        evidence_kind="github_hosted",
        expected_head_sha=HEAD,
        source="https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer/pull/67",
        missing_evidence=["exact_sha_hosted_checks", "safe_shards_unchanged"],
        historical_observation={
            "head_sha": "3b77ad72f5af05340e34caab53c2083070963f69",
            "run_id": "40250889862",
            "artifact_id": "12976898623",
            "claims": {"same_sha_checks_green": False},
        },
    )

    assert receipt["schema"] == SCHEMA
    assert receipt["head_sha"] == HEAD
    assert receipt["evidence_status"] == "UNMEASURABLE"
    assert receipt["decision"] == "NO_GO"
    assert receipt["claims"] == {}
    assert receipt["historical_observation"]["head_sha"] != HEAD
    assert receipt["no_synthetic_substitution"] is True


def test_receipt_hash_is_deterministic() -> None:
    kwargs = dict(
        task_id="H-T195",
        criterion_id="two_hosted_safe_resumes",
        evidence_kind="github_hosted",
        expected_head_sha=HEAD,
        source="https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer",
        missing_evidence=["hosted_run_1", "hosted_run_2"],
    )
    first = build_external_gap_receipt(**kwargs)
    second = build_external_gap_receipt(**kwargs)
    assert first == second
    assert len(first["receipt_sha256"]) == 64


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_head_sha", "bad"),
        ("missing_evidence", []),
        ("task_id", "T-1"),
    ],
)
def test_invalid_gap_is_rejected(field: str, value: object) -> None:
    kwargs = dict(
        task_id="H-T102",
        criterion_id="hosted_checkpoint_resume",
        evidence_kind="github_hosted",
        expected_head_sha=HEAD,
        source="https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer",
        missing_evidence=["run_1"],
    )
    kwargs[field] = value
    with pytest.raises(ValueError):
        build_external_gap_receipt(**kwargs)
