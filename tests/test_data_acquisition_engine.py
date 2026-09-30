from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.data_sources.acquisition_engine import (
    DataAcquisitionEngine,
    DataQualityConfig,
    DataQualityGate,
    DataQualityStatus,
    FetchRequest,
    FetchResult,
    PersistentFetchQueue,
    RequestBudgetManager,
    format_data_quality_assessment,
)
from hl_observer.data_sources.fresh_data_plan import (
    FreshDataPlanRequest,
    build_fresh_data_plan,
    format_fresh_data_plan,
)


def _request(request_id: str = "r1", *, weight: int = 1, priority: float = 0.0, coin: str | None = None) -> FetchRequest:
    return FetchRequest(
        request_id=request_id,
        provider_name="OfficialInfoProvider",
        endpoint="/info",
        request_type="userFillsByTime",
        wallet_address="0x" + "1" * 40,
        coin=coin,
        weight=weight,
        priority=priority,
        network_required=True,
        created_at_ms=1_000,
        ttl_ms=60_000,
    )


def _result(request: FetchRequest, *, now_ms: int = 10_000, confidence: float = 0.95, age_ms: int = 500, latency_ms: int = 100, payload=None) -> FetchResult:
    return FetchResult(
        request=request,
        success=True,
        payload=[{"fill": "ok"}] if payload is None else payload,
        fetched_at_ms=now_ms,
        local_received_at_ms=now_ms + latency_ms,
        exchange_ts_ms=now_ms - age_ms,
        source_confidence_score=confidence,
        transport_latency_ms=latency_ms,
    )


def test_request_budget_blocks_network_when_not_explicit() -> None:
    budget = RequestBudgetManager(network_read_enabled=False, rest_weight_remaining=1200)

    decision = budget.reserve(_request(weight=10))

    assert decision.allowed is False
    assert decision.reason == "NETWORK_READ_DISABLED"
    assert decision.remaining_after == 1200


def test_request_budget_allows_zero_weight_public_streams_without_rest_burn() -> None:
    budget = RequestBudgetManager(network_read_enabled=True, rest_weight_remaining=7)
    request = _request("public", weight=0)

    decision = budget.reserve(request)

    assert decision.allowed is True
    assert decision.requested_weight == 0
    assert decision.remaining_after == 7


def test_persistent_fetch_queue_dedupes_prioritizes_and_persists(tmp_path: Path) -> None:
    queue = PersistentFetchQueue()
    low = _request("low", priority=1)
    high = _request("high", priority=99, coin="ETH")

    assert queue.enqueue(low).reason == "QUEUED"
    assert queue.enqueue(high).reason == "QUEUED"
    assert queue.enqueue(_request("dupe", priority=50)).reason == "DUPLICATE_REQUEST"

    path = queue.save(tmp_path / "fetch_queue.json")
    restored = PersistentFetchQueue.load(path)
    batch = restored.due_batch(now_ms=2_000, max_items=1, budget=RequestBudgetManager(network_read_enabled=True))

    assert [item.request_id for item in batch.selected] == ["high"]
    assert batch.remaining_pending == 1


def test_fetch_queue_keeps_rate_limited_items_pending() -> None:
    queue = PersistentFetchQueue([_request("heavy", weight=2000)])

    batch = queue.due_batch(now_ms=2_000, max_items=1, budget=RequestBudgetManager(network_read_enabled=True, rest_weight_remaining=10))

    assert batch.selected == ()
    assert batch.blocked[0].reason == "RATE_LIMIT_GUARD"
    assert batch.remaining_pending == 1


def test_data_quality_accepts_fresh_high_confidence_payload() -> None:
    gate = DataQualityGate(DataQualityConfig(max_data_age_ms=5_000, min_source_confidence_score=0.7))

    assessment = gate.assess(_result(_request()), now_ms=10_000, proves_pnl=True)

    assert assessment.accepted_for_simulation is True
    assert assessment.status == DataQualityStatus.SIMULATION_READY
    assert assessment.reasons == ()
    assert "ALLOW_FOR_SIGNAL" in assessment.next_action


def test_data_quality_rejects_stale_or_low_confidence_for_pnl() -> None:
    gate = DataQualityGate(DataQualityConfig(max_data_age_ms=3_000, min_source_confidence_score=0.8))

    assessment = gate.assess(_result(_request(), confidence=0.4, age_ms=10_000), now_ms=10_000, proves_pnl=True)

    assert assessment.accepted_for_simulation is False
    assert assessment.status == DataQualityStatus.OBSERVE_ONLY
    assert "STALE_DATA" in assessment.reasons
    assert "LOW_CONFIDENCE_SOURCE" in assessment.reasons
    assert "LOW_CONFIDENCE_CANNOT_PROVE_PNL" in assessment.reasons


def test_data_quality_rejects_empty_payload_as_not_usable_for_signal() -> None:
    gate = DataQualityGate()

    assessment = gate.assess(_result(_request(), payload=[]), now_ms=10_000)

    assert assessment.accepted_for_simulation is False
    assert assessment.status == DataQualityStatus.REJECTED
    assert "SOURCE_PAYLOAD_EMPTY" in assessment.reasons


def test_data_acquisition_engine_marks_terminal_after_quality_assessment() -> None:
    engine = DataAcquisitionEngine(budget=RequestBudgetManager(network_read_enabled=True))
    request = _request()
    assert engine.enqueue(request).reason == "QUEUED"
    assert engine.next_batch(now_ms=2_000, max_items=1).selected[0].request_id == request.request_id

    assessment = engine.assess_result(_result(request), now_ms=10_000, proves_pnl=True)

    assert assessment.accepted_for_simulation is True
    assert request.request_id in engine.queue.completed_request_ids


def test_data_quality_report_is_explicitly_read_only() -> None:
    assessment = DataQualityGate().assess(_result(_request()), now_ms=10_000)

    text = format_data_quality_assessment(assessment)

    assert "data_quality_gate=read_only" in text
    assert "execution=forbidden" in text
    assert "profit_guarantee=false" in text


def test_data_quality_cli_shows_network_budget_and_quality_reasons() -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "data-quality-check",
            "--source-confidence",
            "0.2",
            "--age-ms",
            "10000",
            "--latency-ms",
            "5000",
            "--payload-items",
            "1",
            "--proves-pnl",
        ],
    )

    assert result.exit_code == 0
    assert "budget_allowed=false" in result.output
    assert "NETWORK_READ_DISABLED" in result.output
    assert "LOW_CONFIDENCE_CANNOT_PROVE_PNL" in result.output
    assert "STALE_DATA" in result.output


def test_fresh_data_plan_prioritizes_public_streams_and_caps_hot_wallets() -> None:
    wallets = tuple(f"0x{i:040x}" for i in range(20))

    plan = build_fresh_data_plan(
        FreshDataPlanRequest(
            network_read_enabled=True,
            active_coins=("BTC", "ETH", "HYPE"),
            hot_wallets=wallets,
            rest_weight_remaining=20,
            max_hot_wallets=50,
            gap_recovery=True,
            stale_pressure="CRITICAL",
            now_ms=1_000,
        )
    )
    text = format_fresh_data_plan(plan)

    assert plan.status == "FRESH_DATA_READY"
    assert plan.public_streams == 3
    assert plan.hot_user_streams == 10
    assert plan.rest_gap_recovery_requests > 0
    assert plan.rest_weight_remaining_after >= 0
    assert "hot_user_streams=10/10" in text
    assert "execution=forbidden" in text
    assert "real_orders_created=0" in text


def test_fresh_data_plan_blocks_cleanly_without_network_read() -> None:
    plan = build_fresh_data_plan(
        FreshDataPlanRequest(
            network_read_enabled=False,
            active_coins=("BTC",),
            hot_wallets=("0x" + "a" * 40,),
            now_ms=1_000,
        )
    )

    assert plan.status == "FRESH_DATA_BLOCKED"
    assert dict(plan.blocked_reasons)["NETWORK_READ_DISABLED"] >= 1
