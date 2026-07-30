from hl_observer.signals.distilled_opportunity_detector import (
    DistilledOpportunityConfig,
    DistilledSignalCandidate,
    detect_distilled_opportunities,
)

NOW = 1_000_000


def _candidate(
    wallet: str,
    *,
    coin: str = "HYPE",
    side: str = "LONG",
    age_ms: int = 900,
    edge: float | None = 24.0,
    notional: float = 4_000.0,
    liquidity: float = 0.8,
    degradation: float = 12.0,
    score: float = 80.0,
    public_entity_id: str | None = None,
) -> DistilledSignalCandidate:
    return DistilledSignalCandidate(
        coin=coin,
        side=side,
        leader_wallet=wallet,
        action_type="OPEN_LONG" if side == "LONG" else "OPEN_SHORT",
        event_time_ms=NOW - age_ms,
        leader_notional_usdc=notional,
        edge_remaining_bps=edge,
        liquidity_score=liquidity,
        leader_score=score,
        copy_degradation_bps=degradation,
        source_profile="distilled_test",
        public_entity_id=public_entity_id,
    )


def test_distilled_detector_accepts_fresh_multi_wallet_consensus():
    report = detect_distilled_opportunities(
        [
            _candidate("0x" + "1" * 40),
            _candidate("0x" + "2" * 40),
            _candidate("0x" + "3" * 40, notional=6_000.0),
        ],
        now_ms=NOW,
    )

    assert report.evaluated_candidates == 3
    assert report.rejected_reasons == {}
    assert len(report.opportunities) == 1
    opportunity = report.opportunities[0]
    assert opportunity.coin == "HYPE"
    assert opportunity.side == "LONG"
    assert opportunity.wallet_count == 3
    assert opportunity.entity_cluster_count == 3
    assert opportunity.effective_independent_votes == 1.5
    assert opportunity.independence_measurable is False
    assert opportunity.total_notional_usdc == 14_000.0
    assert opportunity.average_edge_bps == 24.0
    assert opportunity.power_score > 0
    assert "THREE_PLUS_WALLETS" in opportunity.reasons
    assert opportunity.paper_only is True
    assert opportunity.real_execution is False


def test_distilled_detector_refuses_stale_and_missing_edge():
    report = detect_distilled_opportunities(
        [
            _candidate("0x" + "1" * 40, age_ms=10_000),
            _candidate("0x" + "2" * 40, edge=None),
        ],
        now_ms=NOW,
    )

    assert report.opportunities == ()
    assert report.rejected_reasons["stale_signal"] == 1
    assert report.rejected_reasons["edge_missing"] == 1


def test_distilled_detector_refuses_single_wallet_even_with_good_edge():
    report = detect_distilled_opportunities([_candidate("0x" + "1" * 40, edge=80.0)], now_ms=NOW)

    assert report.opportunities == ()
    assert report.rejected_reasons["cluster_below_min_wallets"] == 1


def test_distilled_detector_ranks_stronger_cluster_first_and_limits_total():
    report = detect_distilled_opportunities(
        [
            _candidate("0x" + "1" * 40, coin="BTC", edge=40.0, notional=10_000),
            _candidate("0x" + "2" * 40, coin="BTC", edge=40.0, notional=10_000),
            _candidate("0x" + "3" * 40, coin="SOL", edge=16.0, notional=4_000),
            _candidate("0x" + "4" * 40, coin="SOL", edge=16.0, notional=4_000),
        ],
        now_ms=NOW,
        config=DistilledOpportunityConfig(max_opportunities=1),
    )

    assert len(report.opportunities) == 1
    assert report.opportunities[0].coin == "BTC"
    assert report.opportunities[0].power_score > 0


def test_distilled_detector_rejects_copy_degradation_and_low_liquidity():
    report = detect_distilled_opportunities(
        [
            _candidate("0x" + "1" * 40, degradation=99.0),
            _candidate("0x" + "2" * 40, liquidity=0.05),
        ],
        now_ms=NOW,
    )

    assert report.opportunities == ()
    assert report.rejected_reasons["copy_degradation_too_high"] == 1
    assert report.rejected_reasons["liquidity_too_low"] == 1


def test_distilled_detector_strict_entity_consensus_uses_public_labels():
    candidates = [
        _candidate("0x" + "1" * 40, public_entity_id="desk-a"),
        _candidate("0x" + "2" * 40, public_entity_id="desk-b"),
        _candidate("0x" + "3" * 40, public_entity_id="desk-c"),
    ]
    accepted = detect_distilled_opportunities(
        candidates,
        now_ms=NOW,
        config=DistilledOpportunityConfig(
            min_wallets=3,
            strict_entity_consensus=True,
        ),
    )
    assert len(accepted.opportunities) == 1
    assert accepted.opportunities[0].effective_independent_votes == 3.0

    correlated = [
        _candidate("0x" + "1" * 40, public_entity_id="desk-a"),
        _candidate("0x" + "2" * 40, public_entity_id="desk-a"),
        _candidate("0x" + "3" * 40, public_entity_id="desk-b"),
    ]
    rejected = detect_distilled_opportunities(
        correlated,
        now_ms=NOW,
        config=DistilledOpportunityConfig(
            min_wallets=3,
            strict_entity_consensus=True,
        ),
    )
    assert rejected.opportunities == ()
    assert rejected.rejected_reasons["entity_consensus_below_minimum"] == 1
