"""Port rustjesty min_profit_usd -> plancher profit absolu USD dans calculate_edge.

Vérifie : défaut désactivé (0.0) = aucun changement ; plancher élevé = rejet
avec le reason-code harmonisé EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS ;
plancher minuscule = accepté. Simulation / read-only ; aucun ordre réel.
"""

from hyper_smart_observer.dydx_v4.edge_calculator import calculate_edge


def _edge(min_expected_edge_usdt: float = 0.0, notional: float = 100.0):
    return calculate_edge(
        signal_age_ms=100,
        wallet_count=2,
        leader_winrate=0.60,
        leader_profit_factor=2.0,
        leader_trade_count=60,
        leader_expectancy_usdc=0.30,
        paper_notional_usdc=notional,
        spread_bps=1.0,
        slippage_bps=1.0,
        fee_bps=1.0,
        min_edge_bps=3.0,
        min_expected_edge_usdt=min_expected_edge_usdt,
    )


def test_usd_floor_off_by_default_is_noop():
    # Le plancher désactivé (0.0) ne doit pas modifier la décision bps.
    base = _edge(min_expected_edge_usdt=0.0)
    assert base.accepted is True
    assert base.edge_remaining_bps >= 3.0


def test_usd_floor_blocks_tiny_dollar_edge():
    # Edge net positif en bps mais gain $ négligeable -> rejet explicite.
    r = _edge(min_expected_edge_usdt=1_000_000.0)
    assert r.accepted is False
    assert "EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS" in (r.reject_reason or "")


def test_usd_floor_passes_when_dollar_edge_sufficient():
    # Plancher minuscule -> toujours accepté (comme le baseline bps).
    r = _edge(min_expected_edge_usdt=0.0001)
    assert r.accepted is True
