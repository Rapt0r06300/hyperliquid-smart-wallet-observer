from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

from hl_observer.control_plane.campaign_adapters import (
    AdapterContext,
    _collection_checkpoint_metrics,
    build_command,
    run_one_unit,
)


def _endswith_tool(path: object, suffix: str) -> bool:
    return str(path).replace("\\", "/").endswith(suffix)


def context(kind: str, **partition):
    return AdapterContext(
        campaign_id="c1",
        kind=kind,
        unit_id="u1",
        soft_deadline_epoch=time.time() + 60,
        partition={"code_sha": "a" * 40, **partition},
    )


def test_market_command_uses_real_collector_cli(tmp_path):
    cmd, output = build_command(
        context("market_collection", output_root=str(tmp_path), duration_s=10, coins="BTC")
    )
    assert cmd[0] == sys.executable
    assert _endswith_tool(cmd[1], "tools/collect_cloud_window.py")
    assert "--output" in cmd
    assert "--duration-s" in cmd
    assert "--campaign-unit-json" not in cmd
    assert "--require-l2" in cmd
    assert output is not None


def test_official_archive_uses_existing_backfill_tool(tmp_path):
    cmd, output = build_command(
        context(
            "official_archive_collection",
            output_root=str(tmp_path),
            venue="binance",
            coin="BTC",
            symbol="BTCUSDT",
            start_date="2026-09-24",
        )
    )
    assert _endswith_tool(cmd[1], "tools/collect_official_archive_backfill.py")
    assert output is not None and output.name == "bundle"


def test_okx_archive_campaign_requires_and_forwards_explicit_official_url(tmp_path):
    source_url = (
        "https://static.okx.com/cdn/okex/traderecords/trades/monthly/202609/"
        "BTC-USDT-SWAP-trades-2026-09.zip"
    )
    cmd, _output = build_command(context(
        "official_archive_collection", output_root=str(tmp_path), venue="okx",
        coin="BTC", symbol="BTC-USDT-SWAP", start_date="2026-09-24",
        stream_type="trades", source_url=source_url,
    ))
    assert cmd[cmd.index("--stream-type") + 1] == "trades"
    assert cmd[cmd.index("--source-url") + 1] == source_url
    with pytest.raises(ValueError, match="source_url"):
        build_command(context(
            "official_archive_collection", output_root=str(tmp_path), venue="okx",
            coin="BTC", symbol="BTC-USDT-SWAP", start_date="2026-09-24",
        ))


def test_replay_materializes_only_v2_safe_workspace(tmp_path):
    cmd, output = build_command(
        context("replay", workspace_root=str(tmp_path), families="trades,bbo")
    )
    assert "hl_observer.ops.v2_dataset_bridge" in cmd
    assert "materialize" in cmd
    assert "--families" in cmd
    assert "trades,bbo" in cmd
    assert output == tmp_path


def test_backtest_command_targets_economic_runner(tmp_path):
    cmd, output = build_command(
        context("backtest", workspace_root=str(tmp_path))
    )
    assert _endswith_tool(cmd[1], "tools/run_economic_objective_campaigns.py")
    assert "--no-start-collection" in cmd
    assert output == tmp_path


def test_soft_deadline_refuses_work():
    ctx = AdapterContext("c1", "market_collection", "u1", time.time() - 1, {})
    out = run_one_unit(ctx)
    assert out.status == "CONTINUATION_REQUIRED"
    assert out.progressed is False


def test_subprocess_failure_is_honest(tmp_path):
    class Result:
        returncode = 2
        stdout = ""
        stderr = "quality mismatch"

    out = run_one_unit(
        context("market_collection", output_root=str(tmp_path), duration_s=1),
        runner=lambda *args, **kwargs: Result(),
    )
    assert out.status == "FAILED"
    assert out.payload["failure_category"] == "QUALITY"


def test_copy_vault_subscription_diagnostics_reach_adapter_receipt(tmp_path):
    address = "0x" + "c" * 40

    class Result:
        returncode = 0
        stdout = "collection complete"
        stderr = ""

    def runner(cmd, **_kwargs):
        output = Path(cmd[cmd.index("--output") + 1])
        (output / "manifest.json").write_text(
            json.dumps(
                {
                    "family": "copy_vault_fills",
                    "record_count": 1,
                    "trade_count": 1,
                    "trade_count_exact": True,
                    "bytes": 128,
                    "uncompressed_size_exact": True,
                    "uncompressed_bytes": 256,
                }
            ),
            encoding="utf-8",
        )
        (output / "BUNDLE_INDEX.json").write_text(
            json.dumps(
                {
                    "manifests": ["manifest.json"],
                    "shard_count": 1,
                    "safe_count": 1,
                    "partial_count": 0,
                    "reject_count": 0,
                }
            ),
            encoding="utf-8",
        )
        (output / "collection_summary.json").write_text(
            json.dumps(
                {
                    "duration_s": 10.0,
                    "accepted_frames": 1,
                    "persisted_frames": 1,
                    "l2_frames": 0,
                    "queue_drops": 0,
                    "vault_observation_start_ts_ms": {address: 10_000},
                    "vault_subscription_attempts": {
                        address: [
                            {
                                "type": "userFills",
                                "identity": address,
                                "status": "ACTIVE",
                                "connection_id": "copy-vault-receipt-test",
                                "sent_at_ms": 9_900,
                                "acknowledged_at_ms": 10_000,
                                "timed_out_at_ms": None,
                                "invalidated_at_ms": None,
                                "late_ack": False,
                                "error": None,
                            }
                        ]
                    },
                    "vault_subscription_attempts_dropped": {address: 0},
                    "subscription_diagnostics": {"acknowledged": 1},
                    "l2_diagnostics": {
                        "subscription_ack_mismatches": 0,
                        "invalid_subscription_acks": 0,
                        "markets": {},
                    },
                }
            ),
            encoding="utf-8",
        )
        return Result()

    result = run_one_unit(
        context(
            "copy_vault_collection",
            output_root=str(tmp_path),
            duration_s=10,
            max_vaults=1,
        ),
        runner=runner,
    )

    assert result.status == "COMPLETE"
    receipt = result.payload["collection_metrics"]["copy_vault_subscription"]
    assert receipt["vault_observation_start_ts_ms"] == {address: 10_000}
    assert receipt["vault_subscription_attempts"][address][0]["status"] == "ACTIVE"
    assert receipt["subscription_diagnostics"] == {"acknowledged": 1}


def test_dataset_materialization_transient_http_failure_is_retryable(tmp_path):
    class Result:
        returncode = 2
        stdout = (
            "DATASET_V2_NO_GO: temporary external SAFE shard download "
            "failure: HTTP 503"
        )
        stderr = ""

    out = run_one_unit(
        context("replay", workspace_root=str(tmp_path)),
        runner=lambda *args, **kwargs: Result(),
    )
    assert out.status == "FAILED"
    assert out.payload["reason"] == "adapter_failed"
    assert out.payload["failure_category"] == "TEMPORARY_EXTERNAL"


def test_economic_run_materializes_then_backtests_in_same_unit(tmp_path):
    calls = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def runner(cmd, **kwargs):
        calls.append(list(cmd))
        return Result()

    out = run_one_unit(
        context(
            "backtest",
            workspace_root=str(tmp_path),
            start_ts_ms=1,
            end_ts_ms=2,
        ),
        runner=runner,
    )
    assert out.status == "COMPLETE"
    assert out.progressed is True
    assert len(calls) == 2
    assert "hl_observer.ops.v2_dataset_bridge" in calls[0]
    assert _endswith_tool(calls[1][1], "tools/run_economic_objective_campaigns.py")
    assert out.payload["safe_workspace"] == str(tmp_path)


def test_no_safe_materialization_is_honestly_unavailable(tmp_path):
    calls = []

    class Result:
        returncode = 2
        stdout = ""
        stderr = "DATASET_V2_NO_GO: no SAFE shards match the selection"

    def runner(cmd, **kwargs):
        calls.append(list(cmd))
        return Result()

    out = run_one_unit(
        context("module_pnl_proof", workspace_root=str(tmp_path)),
        runner=runner,
    )
    assert out.status == "UNAVAILABLE"
    assert out.payload["reason"] == "no_safe_dataset_v2"
    assert out.payload["failure_category"] == "DATA_AVAILABILITY"
    assert len(calls) == 1




def test_module_pnl_proof_runs_strict_audit_after_campaign(tmp_path):
    calls = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def runner(cmd, **kwargs):
        calls.append(list(cmd))
        return Result()

    out = run_one_unit(
        context("module_pnl_proof", workspace_root=str(tmp_path), max_shards=2),
        runner=runner,
    )
    assert out.status == "COMPLETE"
    assert len(calls) == 3
    assert "hl_observer.ops.v2_dataset_bridge" in calls[0]
    assert _endswith_tool(calls[1][1], "tools/run_economic_objective_campaigns.py")
    assert _endswith_tool(calls[2][1], "tools/audit_economic_objectives.py")
    assert [phase["name"] for phase in out.payload["phases"]] == [
        "materialize_safe_v2",
        "economic_campaign",
        "module_pnl_audit",
    ]




def _write_economic_audit(tmp_path, *, all_ledgers_valid, all_objectives_met, classifications):
    target = (
        tmp_path
        / "runtime"
        / "reports"
        / "economic_campaigns"
        / "HYPERSMART_ECONOMIC_PROOF_AUDIT.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        __import__("json").dumps(
            {
                "schema_version": "hypersmart.economic_proof_audit.v1",
                "paper_read_only": True,
                "real_execution": False,
                "missing_families": [],
                "all_ledgers_valid": all_ledgers_valid,
                "all_objectives_met": all_objectives_met,
                "families": [
                    {"classification": value} for value in classifications
                ],
            }
        ),
        encoding="utf-8",
    )


def test_module_pnl_unmeasurable_is_complete_stage_not_technical_failure(tmp_path):
    calls = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    class AuditResult:
        returncode = 2
        stdout = "audit written"
        stderr = ""

    def runner(cmd, **kwargs):
        calls.append(list(cmd))
        if _endswith_tool(cmd[1], "tools/audit_economic_objectives.py"):
            _write_economic_audit(
                tmp_path,
                all_ledgers_valid=False,
                all_objectives_met=False,
                classifications=["INVALID"],
            )
            return AuditResult()
        return Result()

    out = run_one_unit(
        context("module_pnl_proof", workspace_root=str(tmp_path)),
        runner=runner,
    )

    assert out.status == "COMPLETE"
    assert out.payload["economic_proof_status"] == "UNMEASURABLE"
    assert out.payload["economic_proof_certifying"] is False
    assert out.payload["phases"][-1]["semantic_status"] == "UNMEASURABLE"
    assert out.payload["phases"][-1]["certifying"] is False


def test_module_pnl_audit_exit_two_without_receipt_remains_technical_failure(tmp_path):
    calls = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    class AuditResult:
        returncode = 2
        stdout = ""
        stderr = "audit failed before receipt"

    def runner(cmd, **kwargs):
        calls.append(list(cmd))
        if _endswith_tool(cmd[1], "tools/audit_economic_objectives.py"):
            return AuditResult()
        return Result()

    out = run_one_unit(
        context("module_pnl_proof", workspace_root=str(tmp_path)),
        runner=runner,
    )

    assert out.status == "FAILED"
    assert out.payload["phase"] == "module_pnl_audit"


def test_module_pnl_more_data_and_kill_are_semantic_not_crashes(tmp_path):
    for classifications, expected in [
        (["INCOMPLETE"], "MORE_DATA"),
        (["VALID_NON_TARGET"], "KILL"),
    ]:
        calls = []

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def runner(cmd, _calls=calls, _classifications=classifications, **kwargs):
            _calls.append(list(cmd))
            if _endswith_tool(cmd[1], "tools/audit_economic_objectives.py"):
                _write_economic_audit(
                    tmp_path,
                    all_ledgers_valid=True,
                    all_objectives_met=False,
                    classifications=_classifications,
                )
            return Result()

        out = run_one_unit(
            context("module_pnl_proof", workspace_root=str(tmp_path)),
            runner=runner,
        )
        assert out.status == "COMPLETE"
        assert out.payload["economic_proof_status"] == expected
        assert out.payload["economic_proof_certifying"] is False


def test_copy_vault_default_respects_hyperliquid_user_limit(tmp_path):
    cmd, _ = build_command(
        context("copy_vault_collection", output_root=str(tmp_path), duration_s=1)
    )
    pos = cmd.index("--max-vaults")
    assert cmd[pos + 1] == "10"


def test_copy_vault_dynamic_shards_cover_full_frozen_universe(tmp_path):
    selection = tmp_path / "selection.json"
    selection.write_text('{"vaults":[]}', encoding="utf-8")
    digest = hashlib.sha256(selection.read_bytes()).hexdigest()
    cmd, _ = build_command(
        context(
            "copy_vault_collection",
            output_root=str(tmp_path / "out"),
            duration_s=1,
            max_vaults=47,
            vault_shard_count=5,
            vault_shard_index=4,
            selection_file=str(selection),
            selection_sha256=digest,
        )
    )
    assert cmd[cmd.index("--max-vaults") + 1] == "47"
    assert cmd[cmd.index("--vault-shard-count") + 1] == "5"
    assert cmd[cmd.index("--vault-shard-index") + 1] == "4"
    assert cmd[cmd.index("--selection-file") + 1] == str(selection)


def test_copy_vault_rejects_partition_above_ten_users_per_lane(tmp_path):
    with pytest.raises(ValueError, match="10 unique users per IP"):
        build_command(
            context(
                "copy_vault_collection",
                output_root=str(tmp_path),
                duration_s=1,
                max_vaults=47,
                vault_shard_count=4,
                vault_shard_index=0,
            )
        )



def test_resume_proof_replay_unit_zero_plans_without_materializing(tmp_path):
    cmd, output = build_command(
        context(
            "replay",
            workspace_root=str(tmp_path),
            resume_proof=True,
            chunk_index=0,
            dataset_selection_id="b" * 64,
            source_collection_epoch=2,
            collection_cutoff_at_utc="2026-09-29T10:56:59Z",
        )
    )
    assert "hl_observer.ops.v2_dataset_bridge" in cmd
    assert "plan" in cmd
    assert "materialize" not in cmd
    assert output == tmp_path


def test_resume_proof_replay_unit_zero_checkpoints_then_unit_one_materializes(tmp_path):
    calls = []

    class Result:
        returncode = 0
        stdout = '{"safe_shards":2,"dataset_ids":["a","b"]}'
        stderr = ""

    def runner(cmd, **kwargs):
        calls.append(list(cmd))
        return Result()

    first = run_one_unit(
        context(
            "replay",
            workspace_root=str(tmp_path),
            resume_proof=True,
            chunk_index=0,
            dataset_selection_id="b" * 64,
            source_collection_epoch=2,
            collection_cutoff_at_utc="2026-09-29T10:56:59Z",
        ),
        runner=runner,
    )
    assert first.status == "CONTINUATION_REQUIRED"
    assert first.progressed is True
    assert first.payload["reason"] == "resume_proof_selection_checkpoint"
    assert "plan" in calls[0]

    calls.clear()
    second = run_one_unit(
        context(
            "replay",
            workspace_root=str(tmp_path),
            resume_proof=True,
            chunk_index=1,
            dataset_selection_id="b" * 64,
            source_collection_epoch=2,
            collection_cutoff_at_utc="2026-09-29T10:56:59Z",
        ),
        runner=runner,
    )
    assert second.status == "COMPLETE"
    assert second.progressed is True
    assert "materialize" in calls[0]

def test_copy_vault_two_speed_separates_broad_universe_from_ws_limit(tmp_path):
    selection = tmp_path / "selection.json"
    selection.write_text('{"vaults":[]}', encoding="utf-8")
    digest = hashlib.sha256(selection.read_bytes()).hexdigest()
    cmd, _ = build_command(
        context(
            "copy_vault_collection",
            output_root=str(tmp_path / "out"),
            duration_s=3500,
            max_vaults=3093,
            max_ws_vaults=10,
            vault_shard_count=1,
            vault_shard_index=0,
            copy_vault_mode="two_speed_broad_rest_priority_ws",
            history_lookback_hours=9.0,
            selection_file=str(selection),
            selection_sha256=digest,
        )
    )
    assert cmd[cmd.index("--max-vaults") + 1] == "3093"
    assert cmd[cmd.index("--max-ws-vaults") + 1] == "10"
    assert cmd[cmd.index("--history-lookback-hours") + 1] == "9.0"
    assert "--two-speed" in cmd


def test_copy_vault_two_speed_rejects_more_than_ten_ws_users(tmp_path):
    with pytest.raises(ValueError):
        build_command(
            context(
                "copy_vault_collection",
                output_root=str(tmp_path),
                max_vaults=3093,
                max_ws_vaults=11,
                copy_vault_mode="two_speed_broad_rest_priority_ws",
            )
        )

def test_collection_checkpoint_metrics_preserve_window_timing(tmp_path):
    (tmp_path / "collection_summary.json").write_text(
        """{
          "started_at_ms": 1000,
          "ended_at_ms": 61000,
          "duration_s": 60.0,
          "accepted_frames": 10,
          "persisted_frames": 10,
          "queue_drops": {}
        }""",
        encoding="utf-8",
    )
    (tmp_path / "BUNDLE_INDEX.json").write_text(
        """{
          "manifests": [],
          "shard_count": 0,
          "safe_count": 0,
          "partial_count": 0,
          "reject_count": 0
        }""",
        encoding="utf-8",
    )

    metrics = _collection_checkpoint_metrics(tmp_path)

    assert metrics["started_at_ms"] == 1000
    assert metrics["ended_at_ms"] == 61000
    assert metrics["duration_s"] == 60.0
    assert metrics["accepted_frames"] == 10
    assert metrics["persisted_frames"] == 10


def test_copy_vault_subscription_diagnostics_reach_collection_receipt(tmp_path):
    address = "0x" + "a" * 40
    summary = {
        "vault_observation_start_ts_ms": {address: 10_000},
        "vault_subscription_attempts": {
            address: [
                {
                    "type": "userFills",
                    "identity": address,
                    "status": "ACTIVE",
                    "connection_id": "copy-vault-test",
                    "sent_at_ms": 9_900,
                    "acknowledged_at_ms": 10_000,
                    "timed_out_at_ms": None,
                    "invalidated_at_ms": None,
                    "late_ack": False,
                    "error": None,
                }
            ]
        },
        "vault_subscription_attempts_dropped": {address: 0},
        "subscription_diagnostics": {"acknowledged": 1, "unmatched_acks": 2},
        "l2_diagnostics": {
            "received_frames": 3,
            "candidate_l2_frames": 2,
            "accepted_frames": 1,
            "rejected_frames": 1,
            "rejected_by_reason": {"invalid_levels": 1},
            "ignored_frames": 1,
            "ignored_by_reason": {"duplicate_snapshot": 1},
            "duplicate_snapshots": 1,
            "reconnects": 1,
            "subscription_ack_mismatches": 1,
            "invalid_subscription_acks": 0,
            "requested_markets": ["BTC"],
            "connection_events": [
                {
                    "event": "connected",
                    "time_ms": 9_700,
                    "connection_id": "copy-l2-test",
                    "markets": ["BTC"],
                },
                {
                    "event": "disconnect",
                    "time_ms": 10_200,
                    "connection_id": "copy-l2-test",
                    "markets": ["BTC"],
                    "error_class": "ConnectionClosedError",
                },
            ],
            "connection_events_dropped": 0,
            "unknown_market_rejections": [
                {
                    "time_ms": 10_150,
                    "connection_id": "copy-l2-test",
                    "reason": "invalid_json",
                }
            ],
            "unknown_market_rejections_dropped": 0,
            "coverage_claim": "NOT_PROVEN",
            "required_market_proof_window_status": "UNAVAILABLE",
            "freshness_policy": "AGE_REPORTED_NO_THRESHOLD_ASSUMED",
            "markets": {
                "BTC": {
                    "received": 2,
                    "candidate_l2_frames": 2,
                    "accepted": 1,
                    "rejected": 1,
                    "duplicates": 0,
                    "rejected_by_reason": {"invalid_levels": 1},
                    "ignored_by_reason": {},
                    "subscription_status": "REJECTED",
                    "subscription_attempts": [
                        {
                            "type": "l2Book",
                            "identity": "BTC",
                            "status": "REJECTED",
                            "connection_id": "copy-l2-test",
                            "sent_at_ms": 9_800,
                            "acknowledged_at_ms": None,
                            "timed_out_at_ms": None,
                            "invalidated_at_ms": None,
                            "late_ack": False,
                            "error": "subscription rejected",
                        }
                    ],
                    "subscription_attempts_dropped": 0,
                    "last_receive_ts_ms": 10_100,
                    "last_receive_age_ms": 100,
                    "last_exchange_ts_ms": 10_000,
                    "last_connection_id": "copy-l2-test",
                    "sequence_continuity_proven": False,
                    "coverage_status": "GAP_OPEN",
                    "proof_window_status": "UNAVAILABLE",
                    "open_gap": {
                        "start_after_receive_ts_ms": 10_000,
                        "detected_at_ms": 10_200,
                        "last_detected_at_ms": 10_200,
                        "reason": "websocket_disconnect",
                        "reasons": ["websocket_disconnect"],
                        "connection_id": "copy-l2-test",
                        "recovery_at_ms": None,
                        "recovery_connection_id": None,
                        "continuity_proven": False,
                    },
                    "gaps": [
                        {
                            "start_after_receive_ts_ms": 10_000,
                            "detected_at_ms": 10_200,
                            "last_detected_at_ms": 10_200,
                            "reason": "websocket_disconnect",
                            "reasons": ["websocket_disconnect"],
                            "connection_id": "copy-l2-test",
                            "recovery_at_ms": None,
                            "recovery_connection_id": None,
                            "continuity_proven": False,
                        }
                    ],
                    "gaps_dropped": 0,
                }
            },
        },
    }
    (tmp_path / "collection_summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )
    (tmp_path / "BUNDLE_INDEX.json").write_text(
        json.dumps(
            {
                "manifests": [],
                "shard_count": 0,
                "safe_count": 0,
                "partial_count": 0,
                "reject_count": 0,
            }
        ),
        encoding="utf-8",
    )

    metrics = _collection_checkpoint_metrics(tmp_path)

    receipt = metrics["copy_vault_subscription"]
    assert receipt["vault_observation_start_ts_ms"] == {address: 10_000}
    assert receipt["vault_subscription_attempts"][address][0]["status"] == "ACTIVE"
    assert receipt["subscription_diagnostics"] == {
        "acknowledged": 1,
        "unmatched_acks": 2,
    }
    assert receipt["l2_subscription"]["markets"]["BTC"][
        "subscription_status"
    ] == "REJECTED"
    l2_receipt = receipt["l2_diagnostics"]
    assert l2_receipt["rejected_by_reason"] == {"invalid_levels": 1}
    assert l2_receipt["connection_events"][1]["error_class"] == "ConnectionClosedError"
    assert l2_receipt["unknown_market_rejections"][0]["reason"] == "invalid_json"
    assert l2_receipt["markets"]["BTC"]["last_receive_age_ms"] == 100
    assert l2_receipt["markets"]["BTC"]["coverage_status"] == "GAP_OPEN"
    assert l2_receipt["required_market_proof_window_status"] == "UNAVAILABLE"
    assert l2_receipt["markets"]["BTC"]["proof_window_status"] == "UNAVAILABLE"
    assert l2_receipt["markets"]["BTC"]["open_gap"]["recovery_at_ms"] is None


def test_invalid_copy_vault_subscription_receipt_values_remain_unknown(tmp_path):
    address = "0x" + "b" * 40
    (tmp_path / "collection_summary.json").write_text(
        json.dumps(
            {
                "vault_observation_start_ts_ms": {address: True},
                "vault_subscription_attempts": {
                    address: [
                        {
                            "type": [],
                            "identity": address,
                            "status": "ACTIVE",
                            "connection_id": "bad-schema",
                            "sent_at_ms": 1,
                            "late_ack": False,
                        }
                    ]
                },
                "subscription_diagnostics": {"acknowledged": True},
                "l2_diagnostics": {
                    "subscription_ack_mismatches": -1,
                    "invalid_subscription_acks": 0,
                    "markets": {"BTC": {"subscription_status": []}},
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "BUNDLE_INDEX.json").write_text(
        json.dumps(
            {
                "manifests": [],
                "shard_count": 0,
                "safe_count": 0,
                "partial_count": 0,
                "reject_count": 0,
            }
        ),
        encoding="utf-8",
    )

    receipt = _collection_checkpoint_metrics(tmp_path)["copy_vault_subscription"]

    assert receipt["vault_observation_start_ts_ms"] is None
    assert receipt["vault_subscription_attempts"] is None
    assert receipt["subscription_diagnostics"] is None
    assert receipt["l2_subscription"] is None
    assert receipt["l2_diagnostics"] is None


def test_collection_checkpoint_metrics_certify_complete_frame_sources(tmp_path):
    summary = {
        "started_at_ms": 1000,
        "ended_at_ms": 61000,
        "duration_s": 60.0,
        "accepted_frames": 10,
        "persisted_frames": 10,
        "queue_drops": {},
    }
    (tmp_path / "collection_summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "l2.json").write_text(
        json.dumps(
            {
                "family": "l2book",
                "record_count": 7,
                "bytes": 128,
                "uncompressed_size_exact": True,
                "uncompressed_bytes": 512,
            }
        ),
        encoding="utf-8",
    )
    (manifest_dir / "trades.json").write_text(
        json.dumps(
            {
                "family": "trades",
                "record_count": 3,
                "bytes": 64,
                "trade_count_exact": True,
                "trade_count": 3,
                "uncompressed_size_exact": True,
                "uncompressed_bytes": 256,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "BUNDLE_INDEX.json").write_text(
        json.dumps(
            {
                "manifests": ["manifests/l2.json", "manifests/trades.json"],
                "shard_count": 2,
                "safe_count": 2,
                "partial_count": 0,
                "reject_count": 0,
            }
        ),
        encoding="utf-8",
    )

    metrics = _collection_checkpoint_metrics(tmp_path)

    assert metrics["accepted_frames"] == 10
    assert metrics["persisted_frames"] == 10
    assert metrics["l2_frames"] == 7
    assert metrics["frame_metrics_complete"] is True


def test_collection_checkpoint_metrics_keep_missing_counts_unknown(tmp_path):
    (tmp_path / "collection_summary.json").write_text(
        json.dumps({"schema": "alina.cloud_collection_window.v1"}),
        encoding="utf-8",
    )
    (tmp_path / "BUNDLE_INDEX.json").write_text(
        json.dumps(
            {
                "manifests": ["manifests/missing.json"],
                "shard_count": 1,
                "safe_count": 1,
                "partial_count": 0,
                "reject_count": 0,
            }
        ),
        encoding="utf-8",
    )

    metrics = _collection_checkpoint_metrics(tmp_path)

    assert metrics["accepted_frames"] is None
    assert metrics["persisted_frames"] is None
    assert metrics["l2_frames"] is None
    assert metrics["bbo_frames"] is None
    assert metrics["queue_drops"] is None
    assert metrics["manifest_inventory_complete"] is False
    assert metrics["frame_metrics_complete"] is False
    assert metrics["trade_count_coverage_complete"] is False


def test_l2_summary_manifest_disagreement_is_not_hidden_by_max(tmp_path):
    (tmp_path / "collection_summary.json").write_text(
        json.dumps(
            {
                "accepted_frames": 8,
                "persisted_frames": 8,
                "l2_frames": 8,
                "queue_drops": {},
            }
        ),
        encoding="utf-8",
    )
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "l2.json").write_text(
        json.dumps({"family": "l2book", "record_count": 7, "bytes": 128}),
        encoding="utf-8",
    )
    (manifest_dir / "trades.json").write_text(
        json.dumps({"family": "trades", "record_count": 1, "bytes": 64}),
        encoding="utf-8",
    )
    (tmp_path / "BUNDLE_INDEX.json").write_text(
        json.dumps(
            {
                "manifests": ["manifests/l2.json", "manifests/trades.json"],
                "shard_count": 2,
                "safe_count": 2,
                "partial_count": 0,
                "reject_count": 0,
            }
        ),
        encoding="utf-8",
    )

    metrics = _collection_checkpoint_metrics(tmp_path)

    assert metrics["l2_frames"] is None
    assert metrics["l2_frames_observed"] == 8
    assert metrics["l2_frames_manifest_records"] == 7
    assert metrics["l2_frames_reconciled"] is False
    assert metrics["frame_metrics_complete"] is False


def test_collection_checkpoint_metrics_preserve_historical_backfill_audit(tmp_path):
    address = "0x" + "a" * 40
    report = {
        "status": "COMPLETE",
        "request_audit_status": "COMPLETE",
        "requested_start_ms": 1_000,
        "requested_end_ms": 2_000,
        "rows": 3,
        "checkpoint_advance_allowed": True,
        "unresolved_gaps": [],
        "retention_cap_reached": False,
        "request_budget_exhausted": False,
        "pending_windows": 0,
        "invalid_fill_count": 0,
        "failed_windows": [],
        "cap_blocked_windows": [],
    }
    index = {
        "manifests": [],
        "shard_count": 1,
        "safe_count": 1,
        "partial_count": 0,
        "reject_count": 0,
        "historical_backfill": {address: report},
    }
    (tmp_path / "BUNDLE_INDEX.json").write_text(
        json.dumps(index), encoding="utf-8"
    )

    metrics = _collection_checkpoint_metrics(tmp_path)

    audit = metrics["historical_backfill_audit"]
    assert audit["source"] == "BUNDLE_INDEX.json"
    assert audit["reports"] == {address: report}
    assert audit["report_count"] == 1
    assert audit["reports_sha256"] == hashlib.sha256(
        json.dumps(
            {address: report},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
