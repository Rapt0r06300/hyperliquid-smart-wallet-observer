"""P1B — exec_model : mode CAUSAL ne replie plus la taxe scalaire de latence (défaut inchangé)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.paper_trading.exec_model import ExecModelConfig, simulate_execution   # noqa: E402
from hl_observer.paper_trading.execution_truth import ExecutionTruth                    # noqa: E402


def _truth():
    return ExecutionTruth.from_levels(coin="BTC", bids=[(99.9, 1000.0)], asks=[(100.1, 1000.0)],
                                      received_ts_ms=1000, source="test")


def _exec(config):
    return simulate_execution(side="BUY", notional_usdc=100.0, mid_price=100.0, latency_sec=5.0,
                              execution_truth=_truth(), decision_ts_ms=1000, strict_book=True,
                              config=config)


def test_defaut_scalar_stress_replie_la_latence():
    r = _exec(ExecModelConfig())                       # défaut = SCALAR_STRESS
    assert r.latency_bps > 0.0                         # comportement historique préservé


def test_mode_causal_ne_replie_pas_la_latence_scalaire():
    r = _exec(ExecModelConfig(latency_mode="CAUSAL"))
    assert r.latency_bps == 0.0                        # latence DANS le carnet causal, pas de taxe scalaire


def test_causal_reduit_le_cout_du_fill_vs_stress():
    stress = _exec(ExecModelConfig())
    causal = _exec(ExecModelConfig(latency_mode="CAUSAL"))
    assert causal.fill_price < stress.fill_price       # BUY : moins de coût replié → fill plus bas
