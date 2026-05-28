from hl_observer.edge.factors import (
    compute_freshness_factor,
    compute_liquidity_penalty,
    compute_crowding_penalty,
    compute_adverse_selection_penalty,
    compute_delay_cost,
    compute_funding_penalty,
    compute_gain_assurance_score
)

def test_compute_freshness_factor():
    assert compute_freshness_factor(0) == 1.0
    assert compute_freshness_factor(3500) == 0.5
    assert compute_freshness_factor(7000) == 0.25
    assert 0 < compute_freshness_factor(100000) < 0.1
    assert compute_freshness_factor(-100) == 1.0

def test_compute_liquidity_penalty():
    # impact_bps = (notional / depth) * 100 bps
    assert compute_liquidity_penalty(1000, 10000) == 10.0
    assert compute_liquidity_penalty(5000, 10000) == 50.0
    assert compute_liquidity_penalty(10000, 10000) == 100.0
    assert compute_liquidity_penalty(20000, 10000) == 100.0
    assert compute_liquidity_penalty(0, 10000) == 0.0
    assert compute_liquidity_penalty(1000, 0) == 100.0

def test_compute_crowding_penalty():
    assert compute_crowding_penalty(1) == 0.0
    assert compute_crowding_penalty(3) == 0.0
    assert compute_crowding_penalty(4) == 3.0
    assert compute_crowding_penalty(10) == 21.0
    assert compute_crowding_penalty(20) == 30.0 # clamped

def test_compute_adverse_selection_penalty():
    # toxicity_score * market_volatility_bps * 0.5
    assert compute_adverse_selection_penalty(0.5, 20.0) == 5.0
    assert compute_adverse_selection_penalty(1.0, 20.0) == 10.0
    assert compute_adverse_selection_penalty(1.0, 100.0) == 25.0 # clamped

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
    # Long, negative funding => no penalty (gain)
    assert compute_funding_penalty("long", -0.0001, 8.0) == 0.0
    # Short, positive funding => no penalty (gain)
    assert compute_funding_penalty("short", 0.0001, 8.0) == 0.0
    # Short, negative funding => penalty
    assert compute_funding_penalty("short", -0.0001, 8.0) == 8.0

def test_compute_gain_assurance_score():
    # Perfect case: edge=30, min=8, fresh=1.0, cons=1.2, liq=100
    # edge_buffer = (30-8)/20 = 1.1 -> 1.0
    # score = 0.3*100 + 0.3*100 + 0.2*1.2*83.33333333333333 + 0.2*100 = 30 + 30 + 20 + 20 = 100
    assert compute_gain_assurance_score(30.0, 8.0, 1.0, 1.2, 100.0) >= 99.9

    # Zero edge
    assert compute_gain_assurance_score(0.0, 8.0, 1.0, 1.2, 100.0) == 0.0

    # Low consistency
    score_low_cons = compute_gain_assurance_score(30.0, 8.0, 1.0, 0.6, 100.0)
    assert score_low_cons < 100.0
