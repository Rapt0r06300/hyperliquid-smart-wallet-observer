from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from hl_observer.backtesting.copy_vault_local_lab import (
    _historical_train_proxy,
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


def test_materialize_safe_workspace_unwraps_verified_copy_vault_assets(tmp_path: Path) -> None:
    recovery = tmp_path / "recovery"
    tag = "data-v2-campaign-copy-vault-test"
    fills_payload = json.dumps({
        "channel": "userFills",
        "data": {"user": "0xabc", "isSnapshot": True, "fills": [{
            "time": 1_000, "coin": "BTC", "px": "100", "sz": "2",
            "side": "B", "dir": "Open Long", "startPosition": "0",
            "oid": 7, "tid": 8, "hash": "0xfill",
        }]},
    }, separators=(",", ":"))
    fill_wrapper = {
        "schema_version": "hypersmart.tick.v1", "channel": "copy_vault_snapshot",
        "instrument": "0xabc", "received_ts_ms": 1_010,
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
    report = {
        "catalog_verification": {"profile": "replay-ready", "safe_catalog_shards": 2},
        "classification": {"missing_or_corrupt_rows": 0, "quarantined_shards": 0},
        "releases": [{"tag": tag, "assets": [
            {"name": fill_name, "size_bytes": fill_size, "sha256": fill_sha,
             "status": "MATERIALIZED_VERIFIED", "verification_status": "VERIFIED"},
            {"name": l2_name, "size_bytes": l2_size, "sha256": l2_sha,
             "status": "MATERIALIZED_VERIFIED", "verification_status": "VERIFIED"},
        ]}],
    }
    (recovery / "RESTORE_REPORT.json").write_text(json.dumps(report), encoding="utf-8")

    result = materialize_safe_workspace(recovery, tmp_path / "workspace")

    assert result["status"] == "READY"
    assert result["unique_fills"] == 1
    assert result["unique_books"] == 1
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
