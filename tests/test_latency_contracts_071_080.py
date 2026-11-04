from __future__ import annotations

from hl_observer.backtesting.copy_vault_causal_selection import freeze_cutoff_receipt
from hl_observer.copy_wallet.copy_latency_profiler import decision_after_receive_receipt
from hl_observer.copy_vault.drop_stale_open_add import stale_action_receipt
from hl_observer.copy_vault.per_vault_queue_cap import queue_cap_receipt
from hl_observer.copy_vault.processing_queue_latency import queue_latency_profile
from hl_observer.paper.latency_model import latency_stress_receipt
from hl_observer.research.metaorder_hazard import markout_by_signal_age_receipt
from hl_observer.research.wallet_info_ratio import segment_edge_by_latency_regime
from hl_observer.simulation.latency_components import latency_components_receipt
from hl_observer.ops.producer_consumer import golden_performance_receipt


def test_071_queue_latency_reports_p95_and_p99() -> None:
    result = queue_latency_profile([1, 2, 3, 4, 5])
    assert result["status"] == "PROVEN"
    assert result["p50_ms"] == 3.0
    assert result["p95_ms"] == 5.0
    assert result["p99_ms"] == 5.0


def test_072_latency_components_reconcile_without_negative_values() -> None:
    result = latency_components_receipt(feed_ms=2.0, order_ms=3.0, inter_leg_ms=4.0)
    assert result["status"] == "PROVEN"
    assert result["total_ms"] == 9.0


def test_073_latency_stress_uses_observed_tail() -> None:
    result = latency_stress_receipt([10, 20, 30, 40])
    assert result["status"] == "PROVEN"
    assert result["stress_ms"] == 40.0
    assert result["optimistic_constant_used"] is False


def test_074_markout_age_receipt_requires_each_bucket() -> None:
    rows = [
        {"signal_age_ms": age, "net_markout_bps": float(age)}
        for age in (50, 150, 550, 1500)
    ]
    result = markout_by_signal_age_receipt(rows, rows, min_rows=1)
    assert result["status"] == "PROVEN"
    assert result["lookahead_free"] is True


def test_075_decision_cannot_precede_receive() -> None:
    assert decision_after_receive_receipt(received_at_ms=100, decision_at_ms=110)["status"] == "PROVEN"
    assert decision_after_receive_receipt(received_at_ms=100, decision_at_ms=90)["status"] == "UNMEASURABLE"


def test_076_stale_open_drops_but_close_is_preserved() -> None:
    assert stale_action_receipt(action="OPEN", age_ms=200, ttl_ms=100)["admissible"] is False
    close = stale_action_receipt(action="CLOSE", age_ms=200, ttl_ms=100)
    assert close["status"] == "PROVEN"
    assert close["reduction_preserved"] is True


def test_077_queue_cap_reports_burst_diagnostics() -> None:
    result = queue_cap_receipt({"vault-a": 5, "vault-b": 1}, cap_per_vault=3)
    assert result["status"] == "PROVEN"
    assert result["accepted"]["vault-a"] == 3
    assert result["dropped"]["vault-a"] == 2
    assert result["diagnostic_preserved"] is True


def test_078_cutoff_freeze_rejects_post_cutoff_rows() -> None:
    result = freeze_cutoff_receipt(
        [{"event_id": "old", "ts_ms": 100}, {"event_id": "new", "ts_ms": 200}], cutoff_ms=150
    )
    assert result["status"] == "PROVEN"
    assert result["admitted_ids"] == ("old",)
    assert result["post_cutoff_rejected"] == 1


def test_079_latency_regime_segments_report_confidence() -> None:
    rows = [
        {"regime": "trend", "latency_ms": float(index), "net_bps": 2.0 + index / 10}
        for index in range(30)
    ]
    result = segment_edge_by_latency_regime(rows, min_rows_per_bucket=1)
    assert result["status"] == "PROVEN"
    assert result["confidence_interval"] == "95_percent"


def test_080_golden_output_prevents_semantic_drift() -> None:
    result = golden_performance_receipt(
        baseline_ms=10.0, optimized_ms=5.0, baseline_output={"signals": [1, 2]}, optimized_output={"signals": [1, 2]}
    )
    assert result["status"] == "PROVEN"
    assert result["speedup"] == 2.0
    assert result["semantic_drift"] is False
