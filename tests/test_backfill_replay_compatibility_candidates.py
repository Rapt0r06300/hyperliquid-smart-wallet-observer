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



def test_verified_historical_archive_recovery_precedes_newer_live_trade_within_family():
    from tools.backfill_replay_compatibility import _candidate_sort_key

    archive = {
        "dataset_id": "archive-binance-btc",
        "family": "trades",
        "source": "binance_usdm_official_archive",
        "release_repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "end_ts_ms": 100,
    }
    newer_live = {
        "dataset_id": "live-binance-btc",
        "family": "trades",
        "source": "binance_public_ws",
        "release_repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "end_ts_ms": 1000000,
    }
    different_family = {
        **newer_live, "family": "bbo", "dataset_id": "live-bbo",
    }
    assert _candidate_sort_key(archive) < _candidate_sort_key(newer_live)
    assert _candidate_sort_key(different_family) < _candidate_sort_key(archive)
    spoof = {**archive, "release_repository": "forged/exchange"}
    assert _candidate_sort_key(spoof) > _candidate_sort_key(archive)


def test_new_global_identity_evidence_retries_prior_failed_replay_receipt():
    dataset_id = "bybit-v3-new-proof"
    row = {
        "dataset_id": dataset_id,
        "family": "trades",
        "venue": "bybit",
        "quality_status": "PARTIAL",
        "replay_compatible": True,
        "trade_count": 3,
        "trade_count_exact": True,
        "unique_trade_count_exact": False,
        "release_repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "release_tag": "data-v2",
        "release_asset": "verified.jsonl.gz",
        "sha256": "a" * 64,
        "bytes": 123,
        "manifest_path": "datasets/quarantine/verified.manifest.json",
    }
    prior = {dataset_id: {
        "replay_compatible": False,
        "verifier_version": backfill.VERIFIER_VERSION,
        "replay_reason": "PREVIOUS_IDENTITY_UNMEASURABLE",
    }}
    assert backfill._candidate(row, prior, {"trades"}) is False
    new_proof = {dataset_id: {
        "trade_count_scanned": 3,
        "unique_trade_count": 3,
        "unique_trade_count_exact": True,
    }}
    assert backfill._candidate(row, prior, {"trades"}, new_proof) is True


def test_replay_backfill_compacts_index_instead_of_indenting_it(tmp_path):
    index_path = tmp_path / "DATA_INDEX.json"
    body = {"shards": [
        {"dataset_id": "one", "quality_status": "PARTIAL", "notes": ["a", "b"]}
    ]}
    backfill._write_json(index_path, body)
    raw = index_path.read_text(encoding="utf-8")
    assert raw == json.dumps(body, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False) + "\n"


def test_no_candidate_replay_wave_preserves_exact_index_bytes(monkeypatch, tmp_path):
    index = tmp_path / "DATA_INDEX.json"
    patch = tmp_path / "REPLAY_COMPAT_PATCH.json"
    original = '{"shards":[],"active_data_status":"SAFE"}\n'
    index.write_text(original, encoding="utf-8")
    monkeypatch.setattr(backfill, "INDEX_PATH", index)
    monkeypatch.setattr(backfill, "PATCH_PATH", patch)
    monkeypatch.setattr(backfill, "ROOT", tmp_path)
    result = backfill.backfill(1, {"trades"})
    assert result["updated"] == 0
    assert index.read_text(encoding="utf-8") == original
    assert patch.is_file()
    saved = json.loads(patch.read_text(encoding="utf-8"))
    assert saved["progress"]["repair_attempts_unique"] == 0
    assert saved["progress"]["temporarily_blocked"] == 0
    assert saved["progress"]["eta_seconds"] is None


def test_replay_progress_counts_outcomes_without_false_repair_claims():
    progress = backfill._build_progress(
        {
            "safe": {
                "verified_from_release": True,
                "replay_compatible": True,
                "asset_size": 10,
                "quality_status_before": "PARTIAL",
                "quality_status_after": "SAFE",
            },
            "still-partial": {
                "verified_from_release": True,
                "replay_compatible": True,
                "asset_size": 20,
                "quality_status_before": "PARTIAL",
                "quality_status_after": "PARTIAL",
            },
            "reject": {
                "verified_from_release": True,
                "replay_compatible": False,
                "asset_size": 30,
                "quality_status_before": "PARTIAL",
                "quality_status_after": "REJECT",
            },
        },
        {"api-blocked": {"attempt_count": 2}},
        {"trades": {"remaining": 4}},
    )
    assert progress["repair_attempts_unique"] == 4
    assert progress["replay_verified"] == 2
    assert progress["repaired_safe"] == 1
    assert progress["certification_rejected"] == 1
    assert progress["temporarily_blocked"] == 1
    assert progress["volume_analyzed_bytes"] == 60
    assert progress["remaining_candidates_known"] == 4
    assert progress["eta_seconds"] is None


def test_replay_refresh_preserves_reversible_compaction(tmp_path):
    from index_run_manifest import (
        CANONICAL_DATA_REPOSITORY,
        hydrate_default_release_repository,
    )
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    for name in ("DATA_CATALOG.json", "DATA_QUALITY_REGISTRY.json"):
        (catalog / name).write_text("{}", encoding="utf-8")
    original = [
        {
            "dataset_id": name, "quality_status": "SAFE",
            "replay_compatible": True,
            "release_repository": CANONICAL_DATA_REPOSITORY,
            "release_tag": "data-v2-bundle",
            "run_manifest_release_tag": "data-v2-run",
            "collection_run_id": "durable-run-abc",
            "sha256": "a" * 64, "event_count": 1,
        }
        for name in ("shard-a", "shard-b")
    ]
    index = {
        "schema": "alina.data_index.v2",
        "shards": original,
    }
    backfill._refresh_catalog(index, tmp_path)
    saved = json.loads((catalog / "DATA_INDEX.json").read_text(encoding="utf-8"))
    assert all("collection_run_id" not in r for r in saved["shards"])
    assert all("run_manifest_release_tag" not in r for r in saved["shards"])
    assert all("release_repository" not in r for r in saved["shards"])
    assert saved["collection_run_ids_by_release"] == {
        "data-v2-bundle": "durable-run-abc",
    }
    assert hydrate_default_release_repository(saved) == original
    # Repeated waves must not inflate or change the canonical index bytes.
    first = (catalog / "DATA_INDEX.json").read_bytes()
    backfill._refresh_catalog(saved, tmp_path)
    assert (catalog / "DATA_INDEX.json").read_bytes() == first

def test_grouped_replay_quota_picks_families_once_in_original_precedence():
    specs = backfill.parse_group_quotas("2:trades,agg_trades;1:bbo;2:*")
    rows = [
        {"dataset_id": "bbo-1", "family": "bbo"},
        {"dataset_id": "bbo-2", "family": "bbo"},
        {"dataset_id": "trade-1", "family": "trades"},
        {"dataset_id": "trade-2", "family": "trades"},
        {"dataset_id": "trade-3", "family": "trades"},
        {"dataset_id": "other-1", "family": "funding"},
    ]
    selected = backfill.select_grouped_candidates(rows, specs)
    ids = [row["dataset_id"] for row in selected]
    assert ids == ["trade-1", "trade-2", "bbo-1", "bbo-2", "trade-3"]
    assert len(ids) == len(set(ids))


def test_grouped_replay_quota_rejects_unbounded_or_invalid_specs():
    import pytest
    for raw in ("", "0:trades", "145:trades", "-1:trades", "1:", "1:*;bad",
                "1:trades;1:../escape", "144:trades;144:bbo;20:l2;1:*"):
        with pytest.raises(ValueError, match="replay group|empty replay"):
            backfill.parse_group_quotas(raw)
    assert backfill.parse_group_quotas("36:trades;36:bbo;18:*") == [
        (36, {"trades"}), (36, {"bbo"}), (18, set())
    ]


def test_replay_workflow_consolidates_repeated_catalogue_rewrites():
    source = (
        ROOT / ".github" / "workflows" / "backfill-replay-compatibility.yml"
    ).read_text(encoding="utf-8")
    wave = source.split("- name: Verify immutable assets for replay", 1)[1].split(
        "- name: Publish replay-proof progress", 1
    )[0]
    assert wave.count("python tools/backfill_replay_compatibility.py") == 1
    assert "--group-quotas" in wave
    assert "--limit 18" not in wave
    assert "python tools/check_dataset_quality.py" in wave

def test_empty_grouped_replay_wave_does_not_rewrite_immutable_catalogue_or_patch(
    monkeypatch, tmp_path,
):
    index = tmp_path / "DATA_INDEX.json"
    patch = tmp_path / "REPLAY_COMPAT_PATCH.json"
    original_index = json.dumps({"shards": [], "active_data_status": "SAFE"}) + "\n"
    original_patch = json.dumps({"schema": "alina.replay_compat_patch.v1", "results": {}, "transient_failures": {}, "progress_by_filter": {}}) + "\n"
    index.write_text(original_index, encoding="utf-8")
    patch.write_text(original_patch, encoding="utf-8")
    monkeypatch.setattr(backfill, "INDEX_PATH", index)
    monkeypatch.setattr(backfill, "PATCH_PATH", patch)
    monkeypatch.setattr(backfill, "ROOT", tmp_path)
    result = backfill.backfill(
        36, set(), group_quotas=backfill.parse_group_quotas("36:trades;36:bbo;36:*")
    )
    assert result == {
        "attempted": 0, "updated": 0, "replayable": 0, "demoted": 0,
        "failed": [], "remaining_candidates_for_filter": 0, "no_change": True,
    }
    assert index.read_text(encoding="utf-8") == original_index
    assert patch.read_text(encoding="utf-8") == original_patch


def test_empty_grouped_workflow_skips_global_metrics_and_git_publication():
    source = (
        ROOT / ".github" / "workflows" / "backfill-replay-compatibility.yml"
    ).read_text(encoding="utf-8")
    wave = source.split("- name: Verify immutable assets for replay", 1)[1].split(
        "- name: Publish replay-proof progress", 1
    )[0]
    assert "REPLAY_WAVE_NOOP" in wave
    assert 'json.load(sys.stdin).get("no_change")' in wave
    assert wave.index("REPLAY_WAVE_NOOP") < wave.index("python tools/build_replay_compatibility_reasons.py")


def test_apply_result_recovers_sha_bound_manifest_from_git_history(tmp_path):
    import subprocess

    dataset_id = "history-recoverable-bbo"
    relative = Path("datasets/quarantine") / f"{dataset_id}.manifest.json"
    manifest_path = tmp_path / relative
    manifest_path.parent.mkdir(parents=True)
    manifest = {
        "schema": "alina.shard_manifest.v2",
        "dataset_id": dataset_id,
        "family": "bbo", "venue": "hyperliquid", "symbol": "BTC",
        "source": "hyperliquid_public_ws",
        "start_ts_ms": 1000, "end_ts_ms": 1001,
        "event_count": 2, "record_count": 2,
        "sha256": "a" * 64, "bytes": 123,
        "collector_version": "original-collector-sha",
        "asset_verified": True,
        "replay_compatible": True,
        "replay_schema_version": "alina.replay.v2",
        "replay_reason": "STRICT_PARSE_CHRONOLOGY_OK",
        "quality_status": "PARTIAL",
        "quality_reasons": ["STALE_CLASSIFICATION"],
        "integrity": {
            "gap_count": 0, "duplicate_count": 0, "duplicates_deduped": True,
            "regression_count": 0, "missing_timestamp_count": 0,
            "missing_monotonic_count": 0, "desync_count": 0,
        },
        "provenance": {
            "public_data_only": True, "authenticated": False,
            "real_execution": False, "transports": ["websocket"],
        },
        "synchronization": {"connection_count": 1},
        "reconciliation": {"status": "SOURCE_CONTINUITY_VERIFIED"},
        "required_channels": [], "observed_channels": ["bbo"],
        "cost_model": {"applicable": False, "ready": False},
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", relative.as_posix()], cwd=tmp_path, check=True)
    subprocess.run([
        "git", "-c", "user.name=tests", "-c", "user.email=tests@example.invalid",
        "commit", "-qm", "store manifest",
    ], cwd=tmp_path, check=True)
    manifest_path.unlink()
    subprocess.run(["git", "add", "-u"], cwd=tmp_path, check=True)
    subprocess.run([
        "git", "-c", "user.name=tests", "-c", "user.email=tests@example.invalid",
        "commit", "-qm", "retire manifest",
    ], cwd=tmp_path, check=True)

    row = {
        "dataset_id": dataset_id, "family": "bbo", "venue": "hyperliquid",
        "symbol": "BTC", "source": "hyperliquid_public_ws",
        "quality_status": "PARTIAL", "replay_compatible": True,
        "manifest_path": relative.as_posix(), "sha256": "a" * 64, "bytes": 123,
    }
    result = {
        "record_count": 2, "replay_compatible": True,
        "replay_schema_version": "alina.replay.v2",
        "replay_reason": "STRICT_PARSE_CHRONOLOGY_OK",
        "verified_from_release": True, "asset_sha256": "a" * 64,
        "asset_size": 123, "verifier_version": backfill.VERIFIER_VERSION,
    }

    backfill._apply_result(row, result, root=tmp_path)

    restored = tmp_path / "datasets/safe" / f"{dataset_id}.manifest.json"
    assert restored.is_file()
    saved = json.loads(restored.read_text(encoding="utf-8"))
    assert saved["quality_status"] == "SAFE"
    assert saved["manifest_recovery"]["source"] == "git_history"
    assert len(saved["manifest_recovery"]["commit_sha"]) == 40
    assert saved["manifest_recovery"]["original_manifest_sha256"]



def test_missing_current_manifest_remains_a_repair_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(backfill, "ROOT", tmp_path)
    row = {
        "dataset_id": "history-recoverable-bbo",
        "family": "bbo",
        "quality_status": "PARTIAL",
        "replay_compatible": True,
        "manifest_path": "datasets/quarantine/history-recoverable-bbo.manifest.json",
        "release_repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "release_tag": "data-v2-example",
        "release_asset": "history-recoverable-bbo.jsonl.gz",
        "sha256": "a" * 64,
        "bytes": 123,
    }

    assert backfill._candidate(dict(row), {}, {"bbo"}) is True
