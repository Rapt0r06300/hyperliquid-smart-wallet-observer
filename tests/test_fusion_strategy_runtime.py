from hl_observer.arbitrage.triangular_graph import TriangularEdge
from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote
from hl_observer.realtime.multi_source_price_stream import PriceEvent
from hl_observer.signals.distilled_opportunity_detector import DistilledSignalCandidate
from hl_observer.strategies.fusion_runtime import FusionRuntimeInput, run_fusion_strategy_runtime


def _payload(**overrides):
    payload = {
        "session_id": "test-fusion",
        "leader_votes": (
            LeaderVote(wallet="0x1", coin="HYPE", side="LONG", score=2.0),
            LeaderVote(wallet="0x2", coin="HYPE", side="LONG", score=1.0),
            LeaderVote(wallet="0x3", coin="HYPE", side="SHORT", score=0.2),
        ),
        "price_events": (
            PriceEvent("hl", "HYPE", 100, 100.1, 1000),
            PriceEvent("cex", "HYPE", 101, 101.1, 1001),
        ),
        "funding_rows": ({"coin": "HYPE", "rates": [0, 0, 0, 0, 0.001]},),
        "triangular_edges": (
            TriangularEdge("USDC", "HYPE", 0.01),
            TriangularEdge("HYPE", "BTC", 0.001),
            TriangularEdge("BTC", "USDC", 101_500),
        ),
        "latencies_ms": (100, 200, 6000),
        "peak_equity": 1000.0,
        "current_equity": 1000.0,
    }
    payload.update(overrides)
    return FusionRuntimeInput(**payload)


def test_fusion_strategy_runtime_routes_multiple_paper_strategies(monkeypatch):
    # Mode recherche locale: valide le bus complet historique (plus le mode normal).
    monkeypatch.setenv("HYPERSMART_EXTERNAL_PROFILES_SCOPE", "all")
    result = run_fusion_strategy_runtime(_payload())
    assert result.session.status == "RUNNING"
    assert result.conflict.decision == "FOLLOW"
    assert result.price_discrepancies
    assert result.funding_signals[0].decision == "FUNDING_SPIKE"
    assert result.triangular_opportunities
    assert len(result.paper_orders) >= 3
    assert result.paper_engine.accepted_count == 1
    assert result.paper_engine.equity_usdt > 0
    assert result.paper_engine.drawdown_usdt >= 0
    assert all(order.paper_only for order in result.paper_orders)
    assert all(order.real_execution is False for order in result.paper_orders)
    # Externes en shadow-only (pivot délibéré ff7aeec) : présents mais NON
    # installés/exécutés, JAMAIS prioritaires sur l'interne. Observation seule.
    assert not result.external_profile_priority
    _sum = result.external_profile_execution_summary
    assert _sum["profiles_total"] >= 34
    assert _sum["profiles_installed"] == 0
    assert _sum["profiles_executed"] == 0
    assert _sum["paper_orders_total"] == 0
    assert result.real_execution is False


def test_fusion_strategy_runtime_can_emit_paper_close_against_open_position():
    result = run_fusion_strategy_runtime(
        _payload(
            leader_votes=(
                LeaderVote(wallet="0x1", coin="HYPE", side="SHORT", score=2.0),
                LeaderVote(wallet="0x2", coin="HYPE", side="SHORT", score=1.5),
                LeaderVote(wallet="0x3", coin="HYPE", side="LONG", score=0.1),
            ),
            open_positions=(
                {
                    "position_key": "paper|HYPE|LONG",
                    "coin": "HYPE",
                    "side": "LONG",
                    "size": 0.5,
                    "entry_price": 100.0,
                    "notional_usdt": 50.0,
                },
            ),
        )
    )

    close_order = next(order for order in result.paper_orders if order.action == "CLOSE")
    assert close_order.coin == "HYPE"
    assert close_order.side == "LONG"
    assert close_order.order_type == "PAPER_CLOSE_SIGNAL"
    assert close_order.strategy_id.startswith("ext_") or close_order.strategy_id.startswith("copy_")
    assert close_order.metadata["close_reason"] == "leader_consensus_flipped_against_open_position"


def test_fusion_strategy_runtime_routes_distilled_opportunity_through_canonical_paper_engine():
    result = run_fusion_strategy_runtime(
        _payload(
            leader_votes=(
                LeaderVote(wallet="0x1", coin="HYPE", side="LONG", score=1.0, observed_at_ms=1000),
                LeaderVote(wallet="0x2", coin="BTC", side="SHORT", score=1.0, observed_at_ms=1000),
            ),
            price_events=(
                PriceEvent("hl", "HYPE", 100, 100.1, 1001),
                PriceEvent("hl", "BTC", 65000, 65010, 1001),
            ),
            funding_rows=(),
            triangular_edges=(),
            distilled_signal_candidates=(
                DistilledSignalCandidate(
                    coin="HYPE",
                    side="LONG",
                    leader_wallet="0x" + "a" * 40,
                    action_type="OPEN_LONG",
                    event_time_ms=1000,
                    leader_notional_usdc=8_000.0,
                    edge_remaining_bps=80.0,
                    liquidity_score=0.95,
                    leader_score=95.0,
                    copy_degradation_bps=8.0,
                    source_profile="distilled_whale_consensus",
                ),
                DistilledSignalCandidate(
                    coin="HYPE",
                    side="LONG",
                    leader_wallet="0x" + "b" * 40,
                    action_type="OPEN_LONG",
                    event_time_ms=1000,
                    leader_notional_usdc=9_000.0,
                    edge_remaining_bps=78.0,
                    liquidity_score=0.93,
                    leader_score=92.0,
                    copy_degradation_bps=9.0,
                    source_profile="distilled_whale_consensus",
                ),
            ),
        )
    )

    assert result.distilled_opportunity_report.opportunities
    assert result.paper_engine.accepted_count == 1
    decision = result.paper_engine.decisions[0]
    assert decision.accepted is True
    assert decision.position is not None
    assert decision.position.coin == "HYPE"
    assert decision.position.side == "LONG"
    assert any(order.metadata.get("source") == "distilled_github_opportunity_detector" for order in result.paper_orders)
    assert "NO_COPY_CONSENSUS" not in result.no_trade_reasons
    assert result.real_execution is False


def test_fusion_strategy_runtime_drawdown_blocks_new_orders():
    result = run_fusion_strategy_runtime(_payload(peak_equity=1000.0, current_equity=900.0))
    assert result.drawdown.triggered is True
    assert result.paper_orders == ()
    assert result.paper_engine.accepted_count == 0
    assert "PORTFOLIO_DRAWDOWN_KILL_SWITCH" in result.no_trade_reasons
    # Externes shadow-only (pivot ff7aeec): aucun profil installé/exécuté.
    assert result.external_profile_execution_summary["profiles_installed"] == 0
    assert result.external_profile_execution_summary["paper_orders_total"] == 0
