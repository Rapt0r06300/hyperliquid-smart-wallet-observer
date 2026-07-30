"""P9.3 — machine à états du hedge cross-venue : hedged / résidu nu / unwind, et agrégats."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import cross_venue_state_machine as M  # noqa: E402


def test_hedge_complet():
    r = M.simuler_hedge(
        leg1={"notional_demande": 100.0, "notional_fill": 100.0, "ts_ms": 1000},
        leg2={"notional_hedge": 100.0, "ts_ms": 1250, "slippage_bps": 3.0},
    )
    assert r["issue"] == M.HEDGED and r["couvert"] is True
    assert r["matched_notional_usd"] == 100.0 and r["residual_notional_usd"] == 0.0
    assert r["hedge_latency_ms"] == 250.0 and r["hedge_slippage_bps"] == 3.0


def test_residu_nu_si_hedge_partiel():
    r = M.simuler_hedge(
        leg1={"notional_demande": 100.0, "notional_fill": 100.0, "ts_ms": 1000},
        leg2={"notional_hedge": 60.0, "ts_ms": 1100},
    )
    assert r["issue"] == M.RESIDUAL_UNHEDGED and r["couvert"] is False
    assert r["matched_notional_usd"] == 60.0 and r["residual_notional_usd"] == 40.0


def test_unwind_si_jambe2_echoue():
    r = M.simuler_hedge(
        leg1={"notional_demande": 100.0, "notional_fill": 80.0, "ts_ms": 1000},
        leg2={"echec": True, "raison_echec": "PROFONDEUR_INSUFFISANTE"},
    )
    assert r["issue"] == M.UNWIND_REQUIRED and r["residual_notional_usd"] == 80.0
    assert r["couvert"] is False and r["leg1_partial"] is True


def test_unwind_si_jambe2_jamais_tentee():
    r = M.simuler_hedge(leg1={"notional_demande": 50.0, "notional_fill": 50.0, "ts_ms": 0})
    assert r["issue"] == M.UNWIND_REQUIRED and r["residual_notional_usd"] == 50.0


def test_no_leg1_si_rien_entre():
    r = M.simuler_hedge(leg1={"notional_demande": 100.0, "notional_fill": 0.0})
    assert r["issue"] == M.NO_LEG1 and r["residual_notional_usd"] == 0.0


def test_latence_incoherente_non_mesuree():
    r = M.simuler_hedge(
        leg1={"notional_demande": 100.0, "notional_fill": 100.0, "ts_ms": 2000},
        leg2={"notional_hedge": 100.0, "ts_ms": 1000},          # hedge AVANT la jambe 1
    )
    assert r["hedge_latency_ms"] is None                        # jamais une latence négative « mesurée »


def test_statistiques_hedge_taux_echec_et_latence():
    resumes = [
        M.simuler_hedge(leg1={"notional_demande": 100, "notional_fill": 100, "ts_ms": 0},
                        leg2={"notional_hedge": 100, "ts_ms": 200}),
        M.simuler_hedge(leg1={"notional_demande": 100, "notional_fill": 100, "ts_ms": 0},
                        leg2={"notional_hedge": 100, "ts_ms": 400}),
        M.simuler_hedge(leg1={"notional_demande": 100, "notional_fill": 100, "ts_ms": 0},
                        leg2={"echec": True}),                    # unwind
        M.simuler_hedge(leg1={"notional_demande": 100, "notional_fill": 0}),   # NO_LEG1 (exclu)
    ]
    stats = M.statistiques_hedge(resumes)
    assert stats["n_hedges_tentes"] == 3                         # le NO_LEG1 est exclu
    assert stats["failed_hedge_rate"] == round(1 / 3, 6)
    assert stats["hedge_latency_mediane_ms"] == 300.0           # médiane de [200, 400]
