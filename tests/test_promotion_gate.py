"""F30 — porte de promotion paper -> testnet : deny-by-default, JAMAIS mainnet."""
from __future__ import annotations

from hl_observer.backtesting.promotion_gate import (
    PROMOUVOIR_TESTNET, RESTE_PAPER, CriteresPromotion, decision_promotion,
)


def _ok(**kw):
    d = dict(
        pnl_paper=100.0,
        profit_factor=1.5,
        n_trades=50,
        survit=True,
        parite_ok=True,
        candidate_id="candidate-A",
        evidence_candidate_id="candidate-A",
        validation_stage="FORWARD_PAPER_POST_FREEZE",
        frozen_at_ms=1_000,
        observed_at_ms=2_000,
        replay_pipeline_hash="pipeline-1",
        forward_pipeline_hash="pipeline-1",
    )
    d.update(kw)
    return d


def test_strategie_positive_et_robuste_est_promue():
    v = decision_promotion(**_ok())
    assert v.decision == PROMOUVOIR_TESTNET and v.motifs == () and v.real_execution is False


def test_pnl_non_positif_reste_paper():
    v = decision_promotion(**_ok(pnl_paper=-1.0))
    assert v.decision == RESTE_PAPER and "PNL_PAPER_NON_POSITIF" in v.motifs


def test_profit_factor_bas_reste_paper():
    assert decision_promotion(**_ok(profit_factor=1.0)).decision == RESTE_PAPER


def test_pas_assez_de_trades_reste_paper():
    assert decision_promotion(**_ok(n_trades=5)).decision == RESTE_PAPER


def test_ne_survit_pas_reste_paper():
    assert "NE_SURVIT_PAS_AUX_STRESS" in decision_promotion(**_ok(survit=False)).motifs


def test_parite_ko_reste_paper():
    assert "PARITE_LIVE_BACKTEST_KO" in decision_promotion(**_ok(parite_ok=False)).motifs


def test_donnee_manquante_deny_by_default():
    v = decision_promotion(pnl_paper=None, profit_factor=None, n_trades=None, survit=None, parite_ok=None)
    assert v.decision == RESTE_PAPER and len(v.motifs) >= 4


def test_holdout_historique_ne_peut_pas_etre_appele_forward():
    v = decision_promotion(**_ok(validation_stage="HISTORICAL_HOLDOUT_HYPOTHESIS_ONLY"))
    assert v.decision == RESTE_PAPER
    assert "HOLDOUT_HISTORIQUE_N_EST_PAS_FORWARD_PAPER" in v.motifs


def test_preuve_d_un_autre_candidat_ne_peut_pas_promouvoir():
    v = decision_promotion(**_ok(evidence_candidate_id="candidate-B"))
    assert v.decision == RESTE_PAPER
    assert "PREUVE_NON_SPECIFIQUE_AU_CANDIDAT" in v.motifs


def test_forward_doit_etre_post_freeze_et_utiliser_le_meme_moteur():
    before_freeze = decision_promotion(**_ok(observed_at_ms=999))
    pipeline_mismatch = decision_promotion(**_ok(forward_pipeline_hash="pipeline-2"))
    assert "OBSERVATION_NON_POSTERIEURE_AU_FREEZE" in before_freeze.motifs
    assert "PARITE_MOTEUR_EVENEMENTS_NON_PROUVEE" in pipeline_mismatch.motifs


def test_jamais_mainnet():
    # quelle que soit l'entree, la decision est PROMOUVOIR_TESTNET ou RESTE_PAPER, JAMAIS mainnet
    for pnl in (-100.0, 0.0, 1e9):
        d = decision_promotion(**_ok(pnl_paper=pnl)).decision
        assert d in (PROMOUVOIR_TESTNET, RESTE_PAPER)
        assert "MAINNET" not in d.upper() and "REAL" not in d.upper()
