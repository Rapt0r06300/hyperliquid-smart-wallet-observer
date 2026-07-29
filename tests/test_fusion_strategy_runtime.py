import pytest

from hl_observer.arbitrage.triangular_graph import TriangularEdge
from hl_observer.collection.l2_snapshot_cache import clear, push_book
from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote
from hl_observer.realtime.multi_source_price_stream import PriceEvent
from hl_observer.signals.distilled_opportunity_detector import DistilledSignalCandidate
from hl_observer.strategies.fusion_runtime import FusionRuntimeInput, run_fusion_strategy_runtime


@pytest.fixture(autouse=True)
def _recorded_execution_books(monkeypatch):
    """Make runtime acceptance deterministic with explicit recorded-real L2."""

    clear()
    monkeypatch.setenv("HYPERSMART_V26_LIVE_BOOK_COSTS", "1")
    for coin, mid in (("HYPE", 100.0), ("BTC", 65_000.0), ("ETH", 1_800.0)):
        push_book(
            coin,
            bids=((mid - 0.01, 10_000.0),),
            asks=((mid + 0.01, 10_000.0),),
            received_ts_ms=999,
            exchange_ts_ms=998,
            source="recorded_hyperliquid_l2_fixture",
        )
    yield
    clear()


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


def test_fusion_strategy_runtime_routes_only_v2_active_paper_strategies(monkeypatch):
    # Même explicitement demandé, l'ancien bus reste hors du chemin économique.
    monkeypatch.setenv("HYPERSMART_EXTERNAL_PROFILES_SCOPE", "all")
    # EDGE FABRIQUE (2026-07-11) : par defaut le bot refuse un edge non empirique.
    # Ce test exerce l'ANCIEN chemin (proxy de vote) -> mode A/B explicite.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    result = run_fusion_strategy_runtime(_payload())
    assert result.session.status == "RUNNING"
    assert result.conflict.decision == "FOLLOW"
    assert result.price_discrepancies
    assert result.funding_signals[0].decision == "FUNDING_SPIKE"
    assert result.triangular_opportunities
    assert len(result.paper_orders) == 1
    assert result.paper_orders[0].metadata["profile_family"] == "cross_exchange_arbitrage"
    assert result.delta_neutral_positions == ()
    assert result.funding_payments == ()
    assert "STRATEGY_SCOPE_BLOCKED_FUNDING_CARRY" in result.no_trade_reasons
    assert "STRATEGY_SCOPE_BLOCKED_TRIANGULAR_ARBITRAGE" in result.no_trade_reasons
    assert "STRATEGY_SCOPE_BLOCKED_EXTERNAL_GITHUB_PROFILES" in result.no_trade_reasons
    assert result.paper_engine.accepted_count == 1
    assert result.paper_engine.equity_usdt > 0
    assert result.paper_engine.drawdown_usdt >= 0
    assert all(order.paper_only for order in result.paper_orders)
    assert all(order.real_execution is False for order in result.paper_orders)
    # Externes en shadow-only (pivot délibéré ff7aeec) : présents mais NON
    # installés/exécutés, JAMAIS prioritaires sur l'interne. Observation seule.
    # Profiles remain visible for auditability, but are shadow-only: none may
    # become priority or request a direct external execution.
    assert all(item.get("priority_over_internal") is False for item in result.external_profile_priority)
    assert all(item.get("direct_external_execution") is False for item in result.external_profile_priority)
    assert all(item.get("paper_only") is True for item in result.external_profile_priority)
    assert all(item.get("read_only") is True for item in result.external_profile_priority)
    _sum = result.external_profile_execution_summary
    assert _sum["profiles_total"] == 0
    assert _sum["paper_orders_total"] == 0
    assert all(row.direct_external_execution is False for row in result.external_profile_executions)
    assert all(row.real_execution is False for row in result.external_profile_executions)
    assert all(row.paper_only is True for row in result.external_profile_executions)
    assert result.real_execution is False


def test_fusion_strategy_runtime_can_emit_paper_close_against_open_position(monkeypatch):
    # EDGE FABRIQUE (2026-07-11) : par defaut le bot refuse desormais un edge non
    # empirique. Ce test exerce l'ANCIEN chemin -> mode A/B explicite.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
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


def test_fusion_strategy_runtime_routes_distilled_opportunity_through_canonical_paper_engine(monkeypatch):
    # EDGE FABRIQUE (2026-07-11) : par defaut le bot refuse desormais un edge non
    # empirique. Ce test exerce l'ANCIEN chemin -> mode A/B explicite.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
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


def test_fusion_strategy_runtime_drawdown_blocks_new_orders(monkeypatch):
    # EDGE FABRIQUE (2026-07-11) : par defaut le bot refuse desormais un edge non
    # empirique. Ce test exerce l'ANCIEN chemin -> mode A/B explicite.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    result = run_fusion_strategy_runtime(_payload(peak_equity=1000.0, current_equity=900.0))
    assert result.drawdown.triggered is True
    assert result.paper_orders == ()
    assert result.paper_engine.accepted_count == 0
    assert "PORTFOLIO_DRAWDOWN_KILL_SWITCH" in result.no_trade_reasons
    # Externes shadow-only : sous kill-switch drawdown, AUCUN profil externe ne produit d'ordre.
    # (On ne force PAS le compteur "profiles_installed" a 0 : les profils restent OBSERVABLES.
    #  Ce qui compte -- et ce qui est verifie -- c'est qu'aucun ordre paper n'en sort.)
    summary = result.external_profile_execution_summary
    assert summary["paper_orders_total"] == 0
    assert summary["profiles_with_paper_orders"] == 0
    assert result.external_profile_execution_summary["paper_orders_total"] == 0


def test_fusion_runtime_selects_real_per_coin_consensus_not_first_row_coin(monkeypatch):
    # EDGE FABRIQUE (2026-07-11) : par defaut le bot refuse desormais un edge non
    # empirique. Ce test exerce l'ANCIEN chemin -> mode A/B explicite.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    result = run_fusion_strategy_runtime(
        _payload(
            leader_votes=(
                LeaderVote(wallet="0xfirst", coin="ETH", side="SHORT", score=1.0, observed_at_ms=990),
                LeaderVote(wallet="0xa", coin="BTC", side="LONG", score=2.5, observed_at_ms=991),
                LeaderVote(wallet="0xb", coin="BTC", side="LONG", score=2.0, observed_at_ms=992),
            ),
            price_events=(
                PriceEvent("hl", "ETH", 1_800.0, 1_800.2, 1_000),
                PriceEvent("hl", "BTC", 65_000.0, 65_001.0, 1_000),
            ),
            funding_rows=(),
            triangular_edges=(),
        )
    )

    assert result.conflict.coin == "BTC"
    assert result.conflict.winning_side == "LONG"
    assert result.paper_engine.accepted_count == 1
    decision = result.paper_engine.decisions[0]
    assert decision.position is not None
    assert decision.position.coin == "BTC"
    assert decision.decision_context["consensus_wallets"] == 2
