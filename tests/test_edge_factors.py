from hl_observer.edge.factors import (
    compute_freshness_factor,
    compute_liquidity_penalty,
    compute_crowding_penalty,
    compute_adverse_selection_penalty,
    compute_delay_cost,
    compute_funding_penalty,
    compute_gain_assurance_score
)
from hl_observer.hyperliquid.schemas import WalletStyle

def test_compute_freshness_factor():
    assert compute_freshness_factor(0) == 1.0
    assert compute_freshness_factor(3500) == 0.5
    assert compute_freshness_factor(7000) == 0.25
    assert 0 < compute_freshness_factor(100000) < 0.1
    assert compute_freshness_factor(-100) == 1.0

def test_compute_freshness_factor_volatility_adjusted():
    # Base: half_life=3500, age=3500 => factor=0.5
    assert compute_freshness_factor(3500, 3500, volatility_index=1.0) == 0.5
    # High volatility: index=2.0 => effective_half_life=1750 => age=1750 should give 0.5
    assert compute_freshness_factor(1750, 3500, volatility_index=2.0) == 0.5
    # Low volatility: index=0.5 => effective_half_life=7000 => age=7000 should give 0.5
    assert compute_freshness_factor(7000, 3500, volatility_index=0.5) == 0.5

def test_compute_liquidity_penalty():
    # impact_bps = sqrt(notional / depth) * 40 bps
    # sqrt(0.1) * 40 = 0.316 * 40 = 12.649
    assert 12.6 < compute_liquidity_penalty(1000, 10000) < 12.7
    # sqrt(1) * 40 = 40.0
    assert compute_liquidity_penalty(10000, 10000) == 40.0
    assert compute_liquidity_penalty(0, 10000) == 0.0
    assert compute_liquidity_penalty(1000, 0) == 100.0

def test_compute_crowding_penalty():
    assert compute_crowding_penalty(1) == 0.0
    assert compute_crowding_penalty(3, total_notional_usdc=0) == 0.0
    # 4 leaders => (4-3)*4 = 4bps
    assert compute_crowding_penalty(4, total_notional_usdc=0) == 4.0
    # $1M notional => (1000000/100000)*3 = 30bps
    assert compute_crowding_penalty(1, total_notional_usdc=1000000) == 30.0

def test_compute_adverse_selection_penalty():
    # toxicity_score * market_volatility_bps * 0.6
    # 0.5 * 20.0 * 0.6 = 6.0
    assert compute_adverse_selection_penalty(0.5, style=WalletStyle.UNKNOWN, market_volatility_bps=20.0) == 6.0
    # Scalper multiplier 2.2 => 6.0 * 2.2 = 13.2
    assert 13.1 < compute_adverse_selection_penalty(0.5, style=WalletStyle.SCALPER_FAST, market_volatility_bps=20.0) < 13.3

def test_compute_delay_cost():
    # age_sec * volatility_bps_per_sec
    assert compute_delay_cost(0) == 0.0
    assert compute_delay_cost(1000, 0.2) == 0.2
    assert compute_delay_cost(5000, 0.2) == 1.0
    assert compute_delay_cost(-1000) == 0.0

def test_compute_funding_penalty():
    # 1bp hourly rate = 0.0001
    # Long, positive funding => penalty
    assert compute_funding_penalty("long", 0.0001, 8.0) == 8.0
    # Long, negative funding => gain (negative penalty)
    assert compute_funding_penalty("long", -0.0001, 8.0) == -8.0

def test_compute_gain_assurance_score():
    # Perfect case: edge=33, min=8, fresh=1.0, cons=1.2, liq=100
    # edge_buffer = (33-8)/25 = 1.0
    # score = 0.35*100 + 0.3*100 + 0.2*1.2*83.33 + 0.15*100 = 35 + 30 + 19.9992 + 15 = 99.9992
    assert compute_gain_assurance_score(33.0, 8.0, 1.0, 1.2, 100.0) >= 99.9

    # Zero edge
    assert compute_gain_assurance_score(0.0, 8.0, 1.0, 1.2, 100.0) == 0.0
