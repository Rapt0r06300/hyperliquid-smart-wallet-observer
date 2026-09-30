"""B2: vague 2 de couverture d'orphelins (modèles risque/exécution paper).

Fige le comportement des modèles de coût réaliste, prêts à câbler dans le
simulateur d'exécution. Réf docs/audit/ORPHAN_MODULES_AUDIT.
"""

from __future__ import annotations

from hl_observer.edge.cost_validation import categorize_cost_level, estimate_total_costs
from hl_observer.paper.partial_fill_model import partial_fill_ratio
from hl_observer.paper.rejection_model import simulated_rejection
from hl_observer.risk.latency_model import latency_penalty_bps
from hl_observer.risk.slippage_model import estimate_slippage_bps


def test_slippage_scales_with_size_over_depth():
    assert estimate_slippage_bps(notional_usdc=1_000, depth_usdc=100_000) == 100.0
    assert estimate_slippage_bps(notional_usdc=100, depth_usdc=0) == 10_000.0   # carnet vide = coût max
    assert estimate_slippage_bps(notional_usdc=500, depth_usdc=50_000) == 100.0


def test_latency_penalty_grows_with_age():
    assert latency_penalty_bps(signal_age_ms=0) == 0.0
    assert latency_penalty_bps(signal_age_ms=2000, bps_per_second=5.0) == 10.0   # 2s × 5 bps
    assert latency_penalty_bps(signal_age_ms=-100) == 0.0


def test_partial_fill_ratio_bounded():
    assert partial_fill_ratio(1_000, 500) == 0.5       # carnet ne couvre que la moitié
    assert partial_fill_ratio(1_000, 5_000) == 1.0     # entièrement rempli
    assert partial_fill_ratio(0, 100) == 0.0
    assert partial_fill_ratio(1_000, 0) == 0.0


def test_rejection_model():
    assert simulated_rejection(api_unstable=True) is True
    assert simulated_rejection(api_unstable=False, min_notional_ok=False) is True
    assert simulated_rejection(api_unstable=False, min_notional_ok=True) is False


def test_total_costs_and_categorization():
    total = estimate_total_costs(taker_fee_bps=4.5, spread_bps=2, slippage_bps=3, latency_bps=1)
    assert total == 10.5
    assert categorize_cost_level(3) == "VERY_LOW"
    assert categorize_cost_level(10.5) == "LOW"
    assert categorize_cost_level(45) == "HIGH"
    assert categorize_cost_level(150) == "PROHIBITIVE"
