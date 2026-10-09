from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

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



def test_release_download_falls_back_to_public_asset_url(monkeypatch,tmp_path):
    calls=[]
    def fake_run(argv,**kwargs):
        calls.append(list(argv))
        if argv[0]=="gh":
            return SimpleNamespace(returncode=1,stderr="API rate limit",stdout="")
        assert argv[0]=="curl"
        output=Path(argv[argv.index("--output")+1])
        output.write_bytes(b"immutable")
        return SimpleNamespace(returncode=0,stderr="",stdout="")

    monkeypatch.setattr(backfill.subprocess,"run",fake_run)
    row={
        "release_repository":"owner/repo",
        "release_tag":"tag with space",
        "release_asset":"asset file.jsonl.gz",
    }
    path=backfill._download(row,tmp_path)
    assert path.read_bytes()==b"immutable"
    assert calls[0][0]=="gh"
    assert calls[1][0]=="curl"
    assert calls[1][-1].endswith(
        "/releases/download/tag%20with%20space/asset%20file.jsonl.gz"
    )



def test_replayable_partial_trade_with_v3_unique_proof_is_repair_candidate():
    dataset_id="bybit-archive-repair"
    row={
        "dataset_id":dataset_id,
        "family":"trades",
        "venue":"bybit",
        "quality_status":"PARTIAL",
        "replay_compatible":True,
        "trade_count":10,
        "trade_count_exact":True,
        "unique_trade_count":None,
        "unique_trade_count_exact":False,
        "release_repository":"owner/repo",
        "release_tag":"tag",
        "release_asset":"asset.jsonl.gz",
        "sha256":"a"*64,
        "bytes":100,
        "manifest_path":"datasets/quarantine/x.manifest.json",
    }
    unique_rows={
        dataset_id:{
            "trade_count_scanned":10,
            "unique_trade_count":10,
            "unique_trade_count_exact":True,
        }
    }
    known={dataset_id:{
        "replay_compatible":True,
        "verifier_version":backfill.VERIFIER_VERSION,
    }}
    assert backfill._candidate(row,known,{"trades"},unique_rows) is True


def test_restore_exact_counts_prefers_current_global_v3_unique_proof(tmp_path):
    catalog=tmp_path/"catalog"
    catalog.mkdir()
    dataset_id="bybit-archive-repair"
    sha="a"*64
    (catalog/"TRADE_COUNT_PATCH.json").write_text(
        json.dumps({"counts":{
            dataset_id:{
                "asset_sha256":sha,
                "trade_count":10,
                "trade_count_exact":True,
                "unique_trade_count":5,
                "unique_trade_count_exact":True,
                "unique_identity_method":"full_native_or_deterministic_composite_string_v2",
            }
        }}),
        encoding="utf-8",
    )
    (catalog/"TRADE_UNIQUE_COUNT_PATCH.json").write_text(
        json.dumps({
            "identity_version":backfill.GLOBAL_IDENTITY_VERSION,
            "counts":{
                dataset_id:{
                    "trade_count_scanned":10,
                    "unique_trade_count":10,
                    "unique_trade_count_exact":True,
                }
            },
        }),
        encoding="utf-8",
    )
    manifest={
        "dataset_id":dataset_id,
        "venue":"bybit",
        "sha256":sha,
    }
    assert backfill._restore_exact_trade_count_evidence(manifest,root=tmp_path) is True
    assert manifest["trade_count"]==10
    assert manifest["trade_count_exact"] is True
    assert manifest["unique_trade_count"]==10
    assert manifest["unique_trade_count_exact"] is True
    assert manifest["unique_identity_method"]==backfill.GLOBAL_IDENTITY_VERSION



def test_rejected_receive_only_copy_vault_enters_verified_backfill(tmp_path, monkeypatch):
    monkeypatch.setattr(backfill, "ROOT", tmp_path)
    dataset_id = "vault-observation-old"
    path = tmp_path / "datasets" / "rejected" / (dataset_id + ".manifest.json")
    path.parent.mkdir(parents=True)
    manifest = {
        "dataset_id": dataset_id,
        "family": "copy_vault_positions",
        "source": "hyperliquid_public_info",
        "asset_verified": True,
        "sha256": "b" * 64,
        "bytes": 150,
        "provenance": {
            "authenticated": False, "public_data_only": True, "real_execution": False,
            "transports": ["https"], "timestamp_semantics": [],
        },
        "release": {
            "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "tag": "data-v2-old",
            "asset_name": "vault.jsonl.gz",
        },
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    row = {
        "dataset_id": dataset_id,
        "family": "copy_vault_positions",
        "quality_status": "REJECT",
        "replay_compatible": False,
        "manifest_path": str(path.relative_to(tmp_path)),
    }
    assert backfill._candidate(row, {}, {"copy_vault_positions"}) is True
    assert row["release_asset"] == "vault.jsonl.gz"
    manifest["source"] = "legacy_unknown_dump"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert backfill._candidate(dict(row), {}, {"copy_vault_positions"}) is False


def test_verified_observation_repair_keeps_original_missing_timestamp_evidence(tmp_path):
    from tools.replay_compatibility import VERIFIER_VERSION
    manifest = {
        "dataset_id": "vault-example",
        "family": "copy_vault_positions", "source": "hyperliquid_public_info",
        "venue": "hyperliquid", "symbol": "0x" + "1" * 40,
        "start_ts_ms": 1000, "end_ts_ms": 1001,
        "sha256": "a" * 64, "bytes": 120, "event_count": 2,
        "collector_version": "test", "asset_verified": True,
        "quality_status": "REJECT",
        "replay_compatible": False, "replay_schema_version": "alina.replay.v2",
        "replay_reason": "MISSING_CAUSAL_TIMESTAMP", "validation_allowed": False,
        "provenance": {
            "public_data_only": True, "authenticated": False,
            "real_execution": False, "transports": ["https"], "timestamp_semantics": [],
        },
        "integrity": {
            "gap_count": 0, "regression_count": 0, "missing_timestamp_count": 2,
            "missing_monotonic_count": 0, "desync_count": 0,
            "duplicate_count": 0, "duplicates_deduped": True,
        },
        "reconciliation": {"status": "UNVERIFIED"},
        "required_channels": [], "observed_channels": ["copy_vault_positions"],
        "cost_model": {"applicable": False, "ready": False},
    }
    path = tmp_path / "datasets" / "rejected" / "vault-example.manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    row = {
        "dataset_id": "vault-example", "family": "copy_vault_positions",
        "quality_status": "REJECT", "manifest_path": str(path.relative_to(tmp_path)),
        "sha256": "a" * 64, "bytes": 120,
    }
    result = {
        "record_count": 2, "replay_compatible": True,
        "replay_schema_version": "alina.replay.v2",
        "replay_reason": "STRICT_PARSE_CHRONOLOGY_OK",
        "receive_only_snapshot_verified": True, "verified_from_release": True,
        "asset_sha256": "a" * 64, "verifier_version": VERIFIER_VERSION,
    }
    backfill._apply_result(row, result, root=tmp_path)
    safe = tmp_path / "datasets" / "safe" / "vault-example.manifest.json"
    assert safe.is_file()
    saved = json.loads(safe.read_text(encoding="utf-8"))
    assert saved["historical_receive_only_repair"]["previous_missing_timestamp_count"] == 2
    assert saved["historical_receive_only_repair"]["exchange_timestamp_invented"] is False
    assert saved["integrity"]["missing_timestamp_count"] == 0
    assert saved["reconciliation"]["status"] == "SNAPSHOT_VERIFIED"
    assert saved["validation_allowed"] is True


def test_observation_repair_requires_verified_release_hash(tmp_path):
    import pytest
    path = tmp_path / "datasets" / "rejected" / "vault-bad.manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"dataset_id": "vault-bad", "sha256": "a" * 64}), encoding="utf-8")
    row = {
        "dataset_id": "vault-bad", "family": "copy_vault_positions",
        "quality_status": "REJECT", "manifest_path": str(path.relative_to(tmp_path)),
        "sha256": "a" * 64,
    }
    with pytest.raises(backfill.BackfillError, match="immutable Release"):
        backfill._apply_result(row, {
            "receive_only_snapshot_verified": True, "replay_compatible": True,
            "asset_sha256": "c" * 64,
        }, root=tmp_path)



def test_compacted_replay_release_hydrates_outer_and_member_locator():
    row = {"release_asset": "", "release_tag": "", "release_repository": ""}
    manifest = {
        "release": {
            "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "release_tag": "data-v2-packed",
            "asset_name": "packed-shards-0000.zip",
            "member_name": "x.jsonl.gz",
            "storage": "zip_entry",
            "remote_size": 200,
            "remote_digest": "sha256:" + "a" * 64,
        },
        "sha256": "b" * 64, "bytes": 50,
    }
    backfill._hydrate_release_fields(row, manifest)
    assert row["release_tag"] == "data-v2-packed"
    assert row["release_asset"] == "x.jsonl.gz"
    assert row["release_container_asset"] == "packed-shards-0000.zip"
    assert row["release_member"] == "x.jsonl.gz"
    assert row["release_remote_digest"] == "sha256:" + "a" * 64



def test_historical_cross_venue_reject_is_inspected_only_with_immutable_release(tmp_path, monkeypatch):
    monkeypatch.setattr(backfill, "ROOT", tmp_path)
    target = tmp_path / "datasets/rejected/cross.manifest.json"
    target.parent.mkdir(parents=True)
    manifest = {
        "dataset_id": "cross", "family": "cross_venue_capacity_tape",
        "source": "cross_venue_derived_capacity", "asset_verified": True,
        "sha256": "a" * 64, "bytes": 123,
        "provenance": {
            "authenticated": False, "public_data_only": True,
            "real_execution": False, "transports": ["derived"],
        },
        "release": {
            "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "tag": "data-v2-cross", "asset_name": "cross.jsonl.gz",
        },
    }
    target.write_text(json.dumps(manifest), encoding="utf-8")
    row = {
        "dataset_id": "cross", "family": "cross_venue_capacity_tape",
        "quality_status": "REJECT", "replay_compatible": False,
        "sha256": "a" * 64, "bytes": 123,
        "manifest_path": "datasets/rejected/cross.manifest.json",
    }
    assert backfill._candidate(dict(row), {}, {"cross_venue_capacity_tape"}) is True
    manifest["asset_verified"] = False
    target.write_text(json.dumps(manifest), encoding="utf-8")
    assert backfill._candidate(dict(row), {}, {"cross_venue_capacity_tape"}) is False
