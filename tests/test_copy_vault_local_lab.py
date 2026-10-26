from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from hl_observer.backtesting import copy_vault_local_lab as local_lab
from hl_observer.backtesting.copy_vault_local_lab import (
    _historical_train_proxy,
    _signal_coverage,
    load_improvement_history,
    materialize_safe_workspace,
    record_frozen_candidate,
    run_historical_trade_replay,
)


def _write_gzip(path: Path, row: dict) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    payload = path.read_bytes()
    return len(payload), hashlib.sha256(payload).hexdigest()


def test_signal_coverage_reports_short_sample_without_inventing_days() -> None:
    day_ms = 86_400_000

    coverage = _signal_coverage([day_ms + 1_000, day_ms + 7_201_000, 2 * day_ms + 1_000, 0])

    assert coverage == {
        "distinct_utc_days": 2,
        "minimum_utc_days_required": 6,
        "signal_start_ms": day_ms + 1_000,
        "signal_end_ms": 2 * day_ms + 1_000,
        "signal_span_hours": 24.0,
    }


def test_safe_catalog_audit_discloses_copy_vault_snapshots_outside_replay_inputs() -> None:
    rows = [
        {"family": "copy_vault_fills", "quality_status": "SAFE"},
        {"family": "copy_vault_l2", "quality_status": "SAFE"},
        {"family": "copy_vault_positions", "quality_status": "SAFE"},
        {"family": "copy_vault_selection", "quality_status": "SAFE"},
        {"family": "copy_vault_positions", "quality_status": "PARTIAL"},
        {"family": "bbo", "quality_status": "SAFE"},
    ]

    audit = local_lab._copy_vault_catalog_audit(rows)

    assert audit["copy_vault_safe_catalog_shards"] == 4
    assert audit["copy_vault_safe_catalog_by_family"] == {
        "copy_vault_fills": 1,
        "copy_vault_l2": 1,
        "copy_vault_positions": 1,
        "copy_vault_selection": 1,
    }
    assert audit["safe_copy_vault_shards_not_used_for_pnl"] == 2
    assert audit["safe_copy_vault_shards_not_used_for_pnl_by_family"] == {
        "copy_vault_positions": 1,
        "copy_vault_selection": 1,
    }


def test_auxiliary_safe_inventory_distinguishes_local_presence_from_hash_verification(
    tmp_path: Path,
) -> None:
    recovery = tmp_path / "runtime" / "recovery" / "full"
    present = recovery / "usable" / "shards" / "release" / "positions.jsonl.gz"
    present.parent.mkdir(parents=True)
    present.write_bytes(b"not hash verified by the replay audit")
    rows = [
        {
            "family": "copy_vault_positions", "quality_status": "SAFE",
            "release_tag": "release", "release_asset": "positions.jsonl.gz",
        },
        {
            "family": "copy_vault_selection", "quality_status": "SAFE",
            "release_tag": "release", "release_asset": "selection.jsonl.gz",
        },
    ]

    inventory = local_lab._copy_vault_auxiliary_inventory(rows, recovery)

    assert inventory == {
        "copy_vault_positions": {
            "catalogue_shards": 1,
            "local_files_present_unverified": 1,
            "local_files_missing": 0,
            "local_files_unsafe": 0,
        },
        "copy_vault_selection": {
            "catalogue_shards": 1,
            "local_files_present_unverified": 0,
            "local_files_missing": 1,
            "local_files_unsafe": 0,
        },
    }


def test_local_campaign_explains_insufficient_signal_days_before_search(
    tmp_path: Path, monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    data_dir = workspace / "runtime" / "data"
    data_dir.mkdir(parents=True)
    tape_manifest = {}
    for name in ("vault_fills.jsonl", "copy_vault_l2_tape.jsonl"):
        payload = b"{}\n"
        (data_dir / name).write_bytes(payload)
        tape_manifest[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest = {
        "paper_read_only": True,
        "real_execution": False,
        "selection_digest": "a" * 64,
        "source_index_sha256": "b" * 64,
        "status": "READY",
        "safe_catalog_status": "SAFE_COMPLETE",
        "replay_inputs_available": True,
        "unique_fills": 2,
        "unique_books": 2,
        "data_complete": True,
        "materialized_tapes": tape_manifest,
    }
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )
    signal_times = [10 * 86_400_000 + 10_000, 11 * 86_400_000 + 10_000]
    metaorders = [
        {"signal_ts_ms": timestamp, "action": "ADD", "coin": "BTC"}
        for timestamp in signal_times
    ]
    books = {"BTC": [{"ts_ms": timestamp - 1_000} for timestamp in signal_times]}

    class Pipeline:
        @staticmethod
        def charger_entrees_alpha_notional_fixe_avec_audit(_workspace):
            return [], {}

    monkeypatch.setattr(local_lab, "_load_pipeline", lambda: Pipeline())
    monkeypatch.setattr(local_lab.cv, "cluster_metaorders", lambda _entries: (metaorders, {}))
    monkeypatch.setattr(
        local_lab.cv,
        "load_observed_books",
        lambda *_args, **_kwargs: (books, {}),
    )

    result = local_lab.run_local_campaign(workspace)

    assert result["status"] == "MORE_DATA"
    assert result["reason"] == "INSUFFICIENT_DISTINCT_SIGNAL_DAYS"
    assert result["signal_coverage"]["distinct_utc_days"] == 2
    assert result["signal_coverage"]["minimum_utc_days_required"] == 6
    assert result["temporally_aligned_add_signals"] == 2
    assert result["candidates_tested"] == 0


def test_local_campaign_identifies_absent_live_forward_fills(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    data_dir = workspace / "runtime" / "data"
    data_dir.mkdir(parents=True)
    tape_manifest = {}
    for name in ("vault_fills.jsonl", "copy_vault_l2_tape.jsonl"):
        payload = b"{}\n"
        (data_dir / name).write_bytes(payload)
        tape_manifest[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(json.dumps({
        "paper_read_only": True,
        "real_execution": False,
        "selection_digest": "a" * 64,
        "source_index_sha256": "b" * 64,
        "status": "MORE_DATA",
        "safe_catalog_status": "SAFE_COMPLETE",
        "replay_inputs_available": True,
        "unique_fills": 1,
        "unique_books": 1,
        "data_complete": False,
        "materialized_tapes": tape_manifest,
    }), encoding="utf-8")
    signal_ms = 10 * 86_400_000 + 10_000
    metaorders = [{"signal_ts_ms": signal_ms, "action": "ADD", "coin": "BTC"}]
    books = {"BTC": [{"ts_ms": signal_ms - 31_000}]}

    class Pipeline:
        @staticmethod
        def charger_entrees_alpha_notional_fixe_avec_audit(_workspace):
            return [], {"live_fill_rows": 0, "causal_live_fill_rows": 0, "historical_fill_rows": 1}

    monkeypatch.setattr(local_lab, "_load_pipeline", lambda: Pipeline())
    monkeypatch.setattr(local_lab.cv, "cluster_metaorders", lambda _entries: (metaorders, {}))
    monkeypatch.setattr(local_lab.cv, "load_observed_books", lambda *_args, **_kwargs: (books, {}))

    result = local_lab.run_local_campaign(workspace)

    assert result["status"] == "MORE_DATA"
    assert result["reason"] == "NO_SAFE_LIVE_FORWARD_FILLS"
    assert result["alignment_reason"] == "NO_CAUSAL_L2_AT_OR_BEFORE_SIGNAL_WITHIN_30_SECONDS"
    assert result["live_fill_rows"] == 0
    assert result["historical_fill_rows"] == 1
    assert result["candidates_tested"] == 0


@pytest.mark.parametrize(
    ("report_status", "gaps", "expected_status", "expected_complete"),
    [
        ("COMPLETE", [], "READY", True),
        (
            "PARTIAL",
            [{"start_ms": 500, "end_ms": 999, "reason": "LOOKBACK_LIMIT"}],
            "MORE_DATA",
            False,
        ),
    ],
)
def test_materialize_safe_workspace_unwraps_verified_copy_vault_assets(
    tmp_path: Path, report_status: str, gaps: list[dict],
    expected_status: str, expected_complete: bool,
) -> None:
    recovery = tmp_path / "runtime" / "recovery" / "full"
    tag = "data-v2-campaign-copy-vault-test"
    fills_payload = json.dumps({
        "channel": "userFills",
        "data": {"user": "0xabc", "isSnapshot": True, "fills": [{
            "time": 1_000, "coin": "BTC", "px": "100", "sz": "2",
            "side": "B", "dir": "Open Long", "startPosition": "0",
            "oid": 7, "tid": 8, "hash": "0xfill", "fee": "0.1",
        }]},
    }, separators=(",", ":"))
    fill_wrapper = {
        "schema_version": "hypersmart.tick.v1",
        "source_id": "hyperliquid_public_userfills_backfill",
        "channel": "copy_vault_snapshot",
        "instrument": "0xabc", "received_ts_ms": 1_010,
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "https", "historical_only": True,
            "forward_evidence_allowed": False,
        },
        "raw_payload": fills_payload,
        "raw_sha256": hashlib.sha256(fills_payload.encode()).hexdigest(),
        "read_only": True, "real_execution": False,
    }
    levels = [[{"px": "99", "sz": "3"}], [{"px": "101", "sz": "4"}]]
    l2_payload = json.dumps({
        "channel": "l2Book", "data": {"coin": "BTC", "time": 2_000, "levels": levels},
    }, separators=(",", ":"))
    l2_wrapper = {
        "schema_version": "hypersmart.tick.v1", "channel": "copy_vault_l2",
        "instrument": "BTC", "exchange_ts_ms": 2_000, "received_ts_ms": 2_010,
        "raw_payload": l2_payload,
        "raw_sha256": hashlib.sha256(l2_payload.encode()).hexdigest(),
        "read_only": True, "real_execution": False,
    }
    fill_name = "hyperliquid-public-userfills-copy-vault-snapshot-test.jsonl.gz"
    l2_name = "hyperliquid-public-copy-l2-copy-vault-l2-btc-test.jsonl.gz"
    fill_size, fill_sha = _write_gzip(recovery / "usable" / "shards" / tag / fill_name, fill_wrapper)
    l2_size, l2_sha = _write_gzip(recovery / "usable" / "shards" / tag / l2_name, l2_wrapper)
    index_rows = []
    for dataset_id, family, asset_name, size, sha in (
        ("cv-fill-test", "copy_vault_snapshot", fill_name, fill_size, fill_sha),
        ("cv-l2-test", "copy_vault_l2", l2_name, l2_size, l2_sha),
    ):
        manifest_path = f"datasets/sharded/safe/aa/bb/{dataset_id}.manifest.json"
        manifest = {
            "schema": "alina.shard_manifest.v2", "quality_status": "SAFE",
            "replay_compatible": True, "asset_verified": True,
            "proof_of_pnl_allowed": False, "dataset_id": dataset_id,
            "family": family, "release_tag": tag, "release_asset": asset_name,
            "bytes": size, "sha256": sha,
            **({
                "historical_fill_observation_count": 1,
                "historical_fill_observation_count_exact": True,
            } if family == "copy_vault_snapshot" else {}),
        }
        manifest_file = tmp_path / manifest_path
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
        index_rows.append({
            "dataset_id": dataset_id, "family": family, "quality_status": "SAFE",
            "replay_compatible": True, "release_tag": tag,
            "release_asset": asset_name, "manifest_path": manifest_path,
            "bytes": size, "sha256": sha,
        })
    catalog = {
        "schema": "alina.data_index.v2",
        "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "shards": index_rows,
    }
    catalog_file = tmp_path / "catalog" / "DATA_INDEX.json"
    catalog_file.parent.mkdir(parents=True, exist_ok=True)
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    report = {
        "status": report_status,
        "request_audit_status": "COMPLETE",
        "checkpoint_advance_allowed": True,
        "retention_cap_reached": False,
        "requested_start_ms": 100,
        "requested_end_ms": 2_000,
        "rows": 1,
        "request_budget_exhausted": False,
        "pending_windows": 0,
        "invalid_fill_count": 0,
        "failed_windows": [],
        "cap_blocked_windows": [],
        "unresolved_gaps": gaps,
    }
    result_payload = {
        "durable_persisted": True,
        "release_tag": tag,
        "stdout": json.dumps({"historical_backfill": {"0xabc": report}}),
    }
    result_sha = hashlib.sha256(
        json.dumps(
            result_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    campaign_dir = tmp_path / "catalog" / "campaigns"
    campaign_dir.mkdir(parents=True, exist_ok=True)
    (campaign_dir / "copy-vault-e1-test.json").write_text(
        json.dumps({
            "campaign_id": "copy-vault-e1-test",
            "kind": "copy_vault_collection",
            "status": "COMPLETE",
            "completed_units": {
                "unit-0": {"sha256": result_sha, "result": result_payload},
            },
        }),
        encoding="utf-8",
    )

    result = materialize_safe_workspace(recovery, tmp_path / "workspace")

    assert result["status"] == expected_status
    assert result["data_complete"] is expected_complete
    assert result["historical_coverage_audit"]["status"] == report_status
    assert len(result["historical_coverage_audit"]["unresolved_gaps"]) == len(gaps)
    assert result["unique_fills"] == 1
    assert result["unique_books"] == 1
    assert result["historical_snapshot_shards"] == 1
    assert result["historical_fill_observations"] == 1
    assert result["historical_unique_fills"] == 1
    assert result["historical_fills_train_only"] is True
    assert result["snapshots_forward_evidence_allowed"] is False
    fill = json.loads((tmp_path / "workspace/runtime/data/vault_fills.jsonl").read_text())
    assert fill["vault"] == "0xabc" and fill["signe"] == 1 and fill["source"] == "REST_BACKFILL"
    book = json.loads((tmp_path / "workspace/runtime/data/copy_vault_l2_tape.jsonl").read_text())
    assert book["causal_observation"] is True
    assert book["bid"] == 99.0 and book["ask"] == 101.0


def test_materialize_safe_workspace_rejects_unverified_asset(tmp_path: Path) -> None:
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    (recovery / "RESTORE_REPORT.json").write_text(json.dumps({
        "catalog_verification": {"profile": "replay-ready", "safe_catalog_shards": 1},
        "classification": {"missing_or_corrupt_rows": 0, "quarantined_shards": 0},
        "releases": [{"tag": "data-v2-campaign-copy-vault-x", "assets": [{
            "name": "bad.jsonl.gz", "size_bytes": 1, "sha256": "0" * 64,
            "status": "FAILED", "verification_status": "FAILED",
        }]}],
    }), encoding="utf-8")

    result = materialize_safe_workspace(recovery, tmp_path / "workspace")

    assert result["status"] == "UNMEASURABLE"
    assert result["verified_assets"] == 0


def test_materialize_distinguishes_verified_shards_from_rejected_payload_rows(
    tmp_path: Path, monkeypatch,
) -> None:
    recovery = tmp_path / "runtime" / "recovery" / "full"
    shard = recovery / "usable" / "shards" / "release" / "l2.jsonl.gz"
    raw_payload = json.dumps({"channel": "unexpected", "data": {}}, separators=(",", ":"))
    wrapper = {
        "read_only": True,
        "real_execution": False,
        "raw_payload": raw_payload,
        "raw_sha256": hashlib.sha256(raw_payload.encode()).hexdigest(),
    }
    _write_gzip(shard, wrapper)
    audit = {
        "status": "SAFE_COMPLETE",
        "reason": None,
        "expected_safe_shards": 1,
        "missing_count": 0,
        "partial_rows_excluded": 0,
        "rejected_count": 0,
    }
    monkeypatch.setattr(
        local_lab,
        "_verified_assets",
        lambda _root, progress=None: ([(shard, {"family": "copy_vault_l2"})], audit),
    )

    result = materialize_safe_workspace(recovery, tmp_path / "workspace")

    assert result["status"] == "UNMEASURABLE"
    assert result["safe_catalog_status"] == "SAFE_COMPLETE"
    assert result["verified_assets"] == result["expected_safe_shards"] == 1
    assert result["missing_shards"] == 0
    assert result["reason"] == "SAFE_PAYLOAD_ROWS_REJECTED"
    assert result["payload_rejected_records"] == 1


def test_frozen_candidate_history_is_append_only_and_idempotent(tmp_path: Path) -> None:
    economic = {
        "freeze_created": True,
        "economically_proven": False,
        "status": "PROMISING",
        "selected_candidate": {"freeze": {"campaign_id": "candidate-1"}},
        "validation": {"daily_mean_net_pnl_usd": 2.5},
    }
    current = {"validation": {"daily_mean_net_pnl_usd": 1.0}}

    first = record_frozen_candidate(tmp_path, "run-1", economic, current)
    second = record_frozen_candidate(tmp_path, "run-1", economic, current)

    assert first == second
    history = load_improvement_history(tmp_path)
    assert len(history) == 1
    assert history[0]["candidate_daily_net_usd"] == 2.5
    assert history[0]["baseline_daily_net_usd"] == 1.0
    assert history[0]["improvement_usd_per_day"] == 1.5
    assert history[0]["classification"] == "CANDIDATE_FROZEN_IMPROVEMENT_MEASURED"
    immutable = tmp_path / "runtime/codex_research/copy_vault_improvements/entries/run-1.json"
    assert immutable.is_file()


def test_historical_train_proxy_scales_to_200_usd_without_claiming_proof(tmp_path: Path) -> None:
    relative = "runtime/reports/train.json"
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "paper_read_only": True,
        "real_execution": False,
        "selected": {
            "core_maximum_notional_usd": 600.0,
            "probe_notional_usd": 75.0,
            "daily_mean_net_pnl_usd": 6.75,
            "statistics": {
                "daily_mean_lcb_usd": 3.375,
                "sample_count": 8,
                "distinct_days": 4,
            },
        },
    }), encoding="utf-8")

    proxy = _historical_train_proxy(tmp_path, {"train_report": relative})

    assert proxy is not None
    assert proxy["daily_net_usd"] == 2.0
    assert proxy["conservative_lcb_usd_per_day"] == 1.0
    assert proxy["economically_proven"] is False


def test_historical_trade_replay_runs_deep_stress_matrix(tmp_path: Path) -> None:
    target = tmp_path / "runtime/reports/economic_campaigns/research_vnext/copy_vault_v21_entry_capacity_daily_lock_train.json"
    target.parent.mkdir(parents=True)
    trades = []
    for index in range(8):
        trades.append({
            "trade_id": f"t{index}", "exit_ts_ms": (index // 2 + 1) * 86_400_000,
            "net_pnl_usd": 1.0 + index, "gross_pnl_usd": 2.0 + index,
            "fees_usd": 0.2, "spread_cost_usd": 0.1,
            "slippage_cost_usd": 0.05, "latency_cost_usd": 0.05,
            "regime_reference_spread_bps": float(index + 1),
            "signed_reference_depth_imbalance": index / 10,
            "observed_latency_ms": 60_000 + index,
            "first_fill_leader_notional_usd": 100 + index,
            "entry_capacity_usd": 200 + index * 25,
            "liquidatable_net": True,
        })
    target.write_text(json.dumps({
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE", "heldout_evaluated": False,
        "paper_read_only": True, "real_execution": False,
        "selected": {
            "eligible": True, "core_maximum_notional_usd": 600.0,
            "probe_notional_usd": 75.0, "trades": trades,
            "statistics": {"sample_count": 8, "distinct_days": 4},
        },
    }), encoding="utf-8")

    result = run_historical_trade_replay(tmp_path, bootstrap_samples=100)

    assert result["status"] == "COMPLETED_EXPLORATORY"
    assert result["trial_count"] >= 10_000
    assert result["mechanism_count"] >= 5
    assert result["source_trade_count"] == 8
    assert result["baseline"]["daily_net_pnl_usd"] is not None
    assert result["economically_proven"] is False
