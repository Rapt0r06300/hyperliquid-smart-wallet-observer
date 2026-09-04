from __future__ import annotations

import pytest

from hl_observer.simulation.vnext_promotion_protocol import (
    build_freeze_manifest,
    consume_post_freeze_once,
    verify_freeze_manifest,
)


def test_freeze_manifest_binds_candidate_dataset_config_family_and_timestamp() -> None:
    candidate = {"variant": "alpha", "threshold_bps": 20.0}
    manifest = build_freeze_manifest(
        family="lead_lag",
        freeze_candidate=candidate,
        dataset_fingerprint="d" * 64,
        config={"capital_usd": 1000.0, "paper_read_only": True},
        frozen_at_ms=1_725_000_000_000,
    )

    assert manifest["schema_version"] == "hypersmart.vnext_freeze_manifest.v1"
    assert manifest["family"] == "lead_lag"
    assert manifest["candidate_sha256"]
    assert manifest["dataset_sha256"] == "d" * 64
    assert manifest["config_sha256"]
    assert manifest["freeze_hash"]
    assert manifest["paper_read_only"] is True
    assert manifest["real_execution"] is False
    assert verify_freeze_manifest(manifest) is True

    mutated = dict(manifest)
    mutated["dataset_sha256"] = "e" * 64
    assert verify_freeze_manifest(mutated) is False


def test_post_freeze_oos_is_one_shot_per_freeze_hash() -> None:
    state: dict[str, object] = {}
    freeze_hash = "f" * 64

    first = consume_post_freeze_once(state, freeze_hash=freeze_hash)
    assert first["post_freeze_oos_consumed"] is True
    assert first["consumed_freeze_hash"] == freeze_hash

    with pytest.raises(RuntimeError, match="already consumed"):
        consume_post_freeze_once(first, freeze_hash=freeze_hash)

    with pytest.raises(RuntimeError, match="different freeze"):
        consume_post_freeze_once(first, freeze_hash="a" * 64)
