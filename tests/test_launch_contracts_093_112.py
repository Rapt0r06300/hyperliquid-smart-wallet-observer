from hl_observer.ops.copy_vault_launch_controls import (
    age_adjusted_cost_receipt,
    boot_phase_timing_receipt,
    collector_cost_cap_receipt,
    core_wallet_scan_receipt,
    cpu_budget_receipt,
    decision_horizon_receipt,
    fee_model_reset_receipt,
    io_pressure_receipt,
    liveness_readiness_receipt,
    maker_l2_execution_receipt,
    net_threshold_vs_daily_target_receipt,
    no_trade_value_receipt,
    poller_latency_receipt,
    position_vs_global_budget_receipt,
    runtime_fee_schedule_receipt,
    source_module_status_receipt,
    stop_trailing_hypothesis_receipt,
    userfills_quota_receipt,
    warmup_overhead_receipt,
    warmup_redundancy_receipt,
)


def test_lch093_distinguishes_threshold_and_absolute_target() -> None:
    result = net_threshold_vs_daily_target_receipt(1.0, daily_target_usd=5.0)
    assert result["status"] == "PROVEN"
    assert result["absolute_daily_target_usd"] == 5.0


def test_lch094_checks_position_and_global_budget_separately() -> None:
    result = position_vs_global_budget_receipt(
        [{"allocation_usd": 10.0}, {"allocation_usd": 15.0}],
        position_budget_usd=20.0,
        global_budget_usd=30.0,
    )
    assert result["status"] == "PROVEN"
    assert position_vs_global_budget_receipt(
        [{"allocation_usd": 21.0}], position_budget_usd=20.0, global_budget_usd=30.0
    )["status"] == "REJECTED"


def test_lch095_requires_maker_and_observed_aggregated_l2() -> None:
    row = {"execution_style": "maker", "l2_aggregated": True, "native_event_id": "l2-1", "observed_at_ms": 10}
    assert maker_l2_execution_receipt([row])["status"] == "PROVEN"
    row["l2_aggregated"] = False
    assert maker_l2_execution_receipt([row])["status"] == "UNMEASURABLE"


def test_lch096_requires_explicit_runtime_fee_schedule() -> None:
    schedule = {
        "maker": {"schedule_id": "m1", "fee_bps": 1.0, "effective_from_ms": 1},
        "taker": {"schedule_id": "t1", "fee_bps": 4.0, "effective_from_ms": 1},
    }
    assert runtime_fee_schedule_receipt(schedule)["status"] == "PROVEN"
    assert runtime_fee_schedule_receipt({"maker": schedule["maker"]})["status"] == "UNMEASURABLE"


def test_lch097_requires_fresh_age_adjusted_costs() -> None:
    assert age_adjusted_cost_receipt(
        [{"signal_ts_ms": 100, "observed_ts_ms": 150, "cost_bps": 2.0}]
    )["status"] == "PROVEN"
    assert age_adjusted_cost_receipt(
        [{"signal_ts_ms": 100, "observed_ts_ms": 100_001, "cost_bps": 2.0}]
    )["status"] == "UNMEASURABLE"


def test_lch098_keeps_stop_and_trailing_as_evidenced_hypotheses() -> None:
    rows = [{"hypothesis_id": "h1", "hypothesis_type": "stop", "evidence_ref": "receipt:1"}]
    assert stop_trailing_hypothesis_receipt(rows)["status"] == "PROVEN"
    assert stop_trailing_hypothesis_receipt([{"hypothesis_type": "trailing"}])["status"] == "UNMEASURABLE"


def test_lch099_preserves_fee_model_on_reset() -> None:
    model = {"fee_bps": 1.0, "maker_rebate_bps": 0.2, "spread_bps": 2.0, "slippage_bps": 3.0}
    assert fee_model_reset_receipt(model, dict(model), reset_event_id="r1")["status"] == "PROVEN"
    changed = dict(model)
    changed["fee_bps"] = 2.0
    assert fee_model_reset_receipt(model, changed, reset_event_id="r1")["status"] == "REJECTED"


def test_lch100_audits_no_trade_value_per_configuration() -> None:
    assert no_trade_value_receipt(
        [{"config_id": "c1", "sample_count": 10, "no_trade_value_bps": 1.5}]
    )["status"] == "PROVEN"
    assert no_trade_value_receipt([{"config_id": "c1", "sample_count": 0}])["status"] == "UNMEASURABLE"


def test_lch101_times_each_boot_phase() -> None:
    assert boot_phase_timing_receipt(
        [{"phase": "collect", "start_ts_ms": 0, "end_ts_ms": 10}, {"phase": "analyze", "start_ts_ms": 10, "end_ts_ms": 20}]
    )["status"] == "PROVEN"
    assert boot_phase_timing_receipt([{"phase": "collect", "start_ts_ms": 10, "end_ts_ms": 1}])["status"] == "UNMEASURABLE"


def test_lch102_rejects_redundant_market_warmup() -> None:
    assert warmup_redundancy_receipt([{"step_id": "w1", "redundant_market_warmup": False}])["status"] == "PROVEN"
    assert warmup_redundancy_receipt([{"step_id": "w1", "redundant_market_warmup": True}])["status"] == "REJECTED"


def test_lch103_caps_bbo_collector_cost() -> None:
    assert collector_cost_cap_receipt([{"collector_id": "bbo", "cost_usd": 1.0}], max_cost_usd=2.0)["status"] == "PROVEN"
    assert collector_cost_cap_receipt([{"collector_id": "bbo", "cost_usd": 3.0}], max_cost_usd=2.0)["status"] == "REJECTED"


def test_lch104_caps_simultaneous_userfills_streams() -> None:
    streams = [{"stream_id": "a", "enabled": True}, {"stream_id": "b", "enabled": True}]
    assert userfills_quota_receipt(streams)["status"] == "PROVEN"
    assert userfills_quota_receipt(streams + [{"stream_id": "c", "enabled": True}])["status"] == "REJECTED"


def test_lch105_checks_cpu_budget_with_salad_active() -> None:
    assert cpu_budget_receipt([{"salad_active": True, "cpu_percent": 30}], max_cpu_percent=50)["status"] == "PROVEN"
    assert cpu_budget_receipt([{"salad_active": True, "cpu_percent": 60}], max_cpu_percent=50)["status"] == "REJECTED"


def test_lch106_calibrates_poller_cadence_from_observed_latency() -> None:
    result = poller_latency_receipt([{"latency_ms": 10}, {"latency_ms": 20}])
    assert result["status"] == "PROVEN"
    assert result["recommended_cadence_ms"] == 25


def test_lch107_rejects_decision_p99_over_horizon() -> None:
    assert decision_horizon_receipt([{"p99_decision_ms": 10, "horizon_ms": 20}])["status"] == "PROVEN"
    assert decision_horizon_receipt([{"p99_decision_ms": 21, "horizon_ms": 20}])["status"] == "REJECTED"


def test_lch108_measures_warmup_cli_overhead() -> None:
    result = warmup_overhead_receipt([{"sync_cli_ms": 100, "batched_cli_ms": 70}])
    assert result["status"] == "PROVEN"
    assert result["total_reduction_ms"] == 30
    assert warmup_overhead_receipt([{"sync_cli_ms": 70, "batched_cli_ms": 100}])["status"] == "REJECTED"


def test_lch109_bounds_core_wallet_scan() -> None:
    row = {"profile": "core", "wallet_count": 50, "full_scan": False}
    assert core_wallet_scan_receipt([row], core_wallet_limit=100)["status"] == "PROVEN"
    row["full_scan"] = True
    assert core_wallet_scan_receipt([row], core_wallet_limit=100)["status"] == "REJECTED"


def test_lch110_measures_recorder_and_ui_io_pressure() -> None:
    row = {"recorder_iops": 10, "ui_iops": 5, "queue_depth": 20}
    assert io_pressure_receipt([row], max_queue_depth=100)["status"] == "PROVEN"
    row["queue_depth"] = 101
    assert io_pressure_receipt([row], max_queue_depth=100)["status"] == "REJECTED"


def test_lch111_keeps_liveness_and_readiness_distinct() -> None:
    assert liveness_readiness_receipt({"live": True}, {"ready": True})["status"] == "PROVEN"
    assert liveness_readiness_receipt({"live": False}, {"ready": True})["status"] == "REJECTED"


def test_lch112_exposes_per_source_module_status() -> None:
    row = {"source": "l2", "module": "collector", "status": "ACTIVE"}
    assert source_module_status_receipt([row])["status"] == "PROVEN"
    assert source_module_status_receipt([{"source": "l2", "module": "collector"}])["status"] == "UNMEASURABLE"
