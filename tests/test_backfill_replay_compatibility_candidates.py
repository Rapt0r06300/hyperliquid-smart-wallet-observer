from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import backfill_replay_compatibility as backfill  # noqa: E402


def _write_manifest(root: Path, *, dataset_id: str, official: bool = True) -> str:
    relative = Path("datasets") / "rejected" / f"{dataset_id}.manifest.json"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "dataset_id": dataset_id,
        "family": "trades",
        "venue": "binance",
        "source": "binance_usdm_official_archive" if official else "legacy_unknown_dump",
        "asset_verified": True,
        "sha256": "a" * 64,
        "bytes": 1234,
        "provenance": {
            "public_data_only": True,
            "authenticated": False,
            "real_execution": False,
            "transports": ["https"],
            "timestamp_semantics": ["historical_exchange_time_only"],
        },
        "release": {
            "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "tag": "archive-v2-test",
            "asset_name": f"{dataset_id}.jsonl.gz",
        },
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return relative.as_posix()


def test_rejected_official_archive_candidate_is_hydrated_from_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(backfill, "ROOT", tmp_path)
    dataset_id = "binance-official-archive-trades-btc-test"
    row = {
        "dataset_id": dataset_id,
        "family": "trades",
        "quality_status": "REJECTED",
        "replay_compatible": False,
        "manifest_path": _write_manifest(tmp_path, dataset_id=dataset_id),
    }

    assert backfill._candidate(row, {}, {"trades"}) is True
    assert row["release_repository"] == "Rapt0r06300/hyperliquid-smart-wallet-observer"
    assert row["release_tag"] == "archive-v2-test"
    assert row["release_asset"] == f"{dataset_id}.jsonl.gz"
    assert row["sha256"] == "a" * 64
    assert row["bytes"] == 1234


def test_non_official_rejected_dump_stays_excluded(monkeypatch, tmp_path):
    monkeypatch.setattr(backfill, "ROOT", tmp_path)
    dataset_id = "legacy-trades-btc-test"
    row = {
        "dataset_id": dataset_id,
        "family": "trades",
        "quality_status": "REJECT",
        "replay_compatible": False,
        "manifest_path": _write_manifest(tmp_path, dataset_id=dataset_id, official=False),
    }

    assert backfill._candidate(row, {}, {"trades"}) is False


def test_stale_failed_receipt_is_retried_after_verifier_upgrade(monkeypatch, tmp_path):
    monkeypatch.setattr(backfill, "ROOT", tmp_path)
    dataset_id = "binance-official-archive-trades-btc-retry"
    row = {
        "dataset_id": dataset_id,
        "family": "trades",
        "quality_status": "REJECT",
        "replay_compatible": False,
        "manifest_path": _write_manifest(tmp_path, dataset_id=dataset_id),
    }
    known = {
        dataset_id: {
            "replay_compatible": False,
            "replay_reason": "INVALID_RECORD",
        }
    }
    assert backfill._candidate(row, known, {"trades"}) is True


def test_current_failed_receipt_does_not_loop(monkeypatch, tmp_path):
    monkeypatch.setattr(backfill, "ROOT", tmp_path)
    dataset_id = "binance-official-archive-trades-btc-current"
    row = {
        "dataset_id": dataset_id,
        "family": "trades",
        "quality_status": "REJECT",
        "replay_compatible": False,
        "manifest_path": _write_manifest(tmp_path, dataset_id=dataset_id),
    }
    known = {
        dataset_id: {
            "replay_compatible": False,
            "replay_reason": "INVALID_RECORD",
            "verifier_version": backfill.VERIFIER_VERSION,
        }
    }
    assert backfill._candidate(row, known, {"trades"}) is False
