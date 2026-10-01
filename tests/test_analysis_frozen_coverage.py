from __future__ import annotations

import hashlib
import json
import os
import subprocess

from tools.build_analysis_frozen_coverage_receipt import _digest, build_receipt


def _git(root, *args, env=None):
    subprocess.run(["git", "-C", str(root), *args], check=True, env=env)


def test_builder_uses_exact_pre_cutoff_index_not_later_global_shards(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "catalog/campaigns").mkdir(parents=True)
    (tmp_path / "control").mkdir()
    index_bytes = b'{"schema":"index","items":[1]}\n'
    (tmp_path / "catalog/DATA_INDEX.json").write_bytes(index_bytes)
    coverage = {
        "valid_record_count_exact": True,
        "unique_record_count_exact": True,
        "trade_count_exact": True,
        "unique_trade_count_exact": True,
        "uncompressed_bytes_exact": True,
        "replayable_shards": 2,
    }
    health = {
        "schema_version": "alina.dataset_health_receipt.v1",
        "dataset_commit": "1" * 40,
        "coverage": coverage,
    }
    health["receipt_digest"] = _digest(health)
    (tmp_path / "catalog/DATASET_HEALTH_RECEIPT.json").write_text(
        json.dumps(health), encoding="utf-8"
    )
    _git(tmp_path, "add", ".")
    env = dict(os.environ, GIT_AUTHOR_DATE="2026-09-30T14:00:00Z", GIT_COMMITTER_DATE="2026-09-30T14:00:00Z")
    _git(tmp_path, "commit", "-m", "exact frozen index", env=env)
    frozen_commit = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    health["dataset_commit"] = frozen_commit
    health.pop("receipt_digest")
    health["receipt_digest"] = _digest(health)
    (tmp_path / "catalog/DATASET_HEALTH_RECEIPT.json").write_text(
        json.dumps(health), encoding="utf-8"
    )
    _git(tmp_path, "add", ".")
    env = dict(os.environ, GIT_AUTHOR_DATE="2026-09-30T14:01:00Z", GIT_COMMITTER_DATE="2026-09-30T14:01:00Z")
    _git(tmp_path, "commit", "-m", "bind exact receipt", env=env)

    cutoff = "2026-09-30T17:06:32Z"
    index_sha = hashlib.sha256(index_bytes).hexdigest()
    selection = hashlib.sha256(f"4|{cutoff}|{index_sha}".encode()).hexdigest()
    phase = {
        "phase": "ANALYZE",
        "epoch": 5,
        "source_collection_epoch": 4,
        "collection_cutoff_at_utc": cutoff,
    }
    (tmp_path / "control/alina-phase.json").write_text(json.dumps(phase), encoding="utf-8")
    materialization = json.dumps({
        "index_sha256": index_sha,
        "dataset_selection_id": selection,
        "events": 3,
        "safe_shards": 1,
    })
    campaign = {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "analysis-e5-replay-v2",
        "kind": "replay",
        "creation_phase": "ANALYZE",
        "status": "COMPLETE",
        "phase_epoch": 5,
        "source_collection_epoch": 4,
        "collection_cutoff_at_utc": cutoff,
        "dataset_selection_id": selection,
        "updated_at": "2026-09-30T17:16:00Z",
        "terminal_evidence_digest": "e" * 64,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "completed_units": {"0": {"result": {"stdout": materialization}}},
    }
    (tmp_path / "catalog/campaigns/analysis-e5-replay-v2.json").write_text(
        json.dumps(campaign), encoding="utf-8"
    )
    degraded = dict(health)
    degraded["coverage"] = dict(coverage, unique_trade_count_exact=False)
    degraded.pop("receipt_digest")
    degraded["receipt_digest"] = _digest(degraded)
    (tmp_path / "catalog/DATASET_HEALTH_RECEIPT.json").write_text(
        json.dumps(degraded), encoding="utf-8"
    )
    _git(tmp_path, "add", ".")
    env = dict(os.environ, GIT_AUTHOR_DATE="2026-09-30T18:00:00Z", GIT_COMMITTER_DATE="2026-09-30T18:00:00Z")
    _git(tmp_path, "commit", "-m", "post-cutoff shards", env=env)

    receipt = build_receipt(tmp_path)

    assert receipt["dataset_selection_id"] == selection
    assert receipt["coverage"]["unique_trade_count_exact"] is True
    assert receipt["coverage"]["replayable_shards"] == 2
    assert receipt["health_evidence_commit"] != subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
