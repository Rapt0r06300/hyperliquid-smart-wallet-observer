"""Le pipeline anti-lookahead : UNE porte qui compose AST + purge/embargo + PBO. Deny-by-default."""
from __future__ import annotations

from hl_observer.backtesting.anti_lookahead_pipeline import (
    MOTIF_AST_SALE,
    MOTIF_COUPE_INVALIDE,
    MOTIF_OK,
    MOTIF_OVERFIT,
    verifier_backtest,
)

# 20 candidats étalés dans le temps → coupe train/test valide.
CANDIDATS = [{"recorded_at": float(t)} for t in range(0, 2000, 100)]
# 60 PnL positifs peu volatils → Sharpe élevé, survit à la déflation à 1 essai.
PNLS_FORTS = [1.0, 0.8, 1.2, 0.9, 1.1] * 12


def test_un_backtest_propre_passe_les_trois_portes() -> None:
    v = verifier_backtest(
        candidats=CANDIDATS, horizon_min=1.0, embargo_min=0.0,
        pnls_test=PNLS_FORTS, n_essais=1, source_du_signal=None,
    )
    assert v.coupe_valide is True
    assert v.overfit_survit is True
    assert v.accepte is True
    assert MOTIF_OK in v.motifs


def test_une_coupe_vide_apres_purge_est_refusee() -> None:
    v = verifier_backtest(
        candidats=[{"recorded_at": 0.0}], horizon_min=1.0, embargo_min=0.0,
        pnls_test=PNLS_FORTS, n_essais=1,
    )
    assert v.coupe_valide is False
    assert v.accepte is False
    assert MOTIF_COUPE_INVALIDE in v.motifs


def test_un_edge_qui_ne_survit_pas_a_la_deflation_est_refuse() -> None:
    # trop peu de trades → l'anti-overfit refuse (variance de l'estimateur), donc le pipeline aussi.
    v = verifier_backtest(
        candidats=CANDIDATS, horizon_min=1.0, embargo_min=0.0,
        pnls_test=[0.1, 0.1, 0.1], n_essais=1,
    )
    assert v.overfit_survit is False
    assert v.accepte is False
    assert MOTIF_OVERFIT in v.motifs


def test_un_signal_qui_lit_le_futur_est_attrape_par_l_AST() -> None:
    # agrégat GLOBAL sur toute la série (futur inclus) au lieu d'une fenêtre passée → lookahead.
    source_qui_triche = "def s(prices):\n    return prices.mean()\n"
    v = verifier_backtest(
        candidats=CANDIDATS, horizon_min=1.0, embargo_min=0.0,
        pnls_test=PNLS_FORTS, n_essais=1, source_du_signal=source_qui_triche,
    )
    assert v.ast_verifie is True
    assert v.ast_propre is False
    assert v.n_suspicions >= 1
    assert v.accepte is False
    assert MOTIF_AST_SALE in v.motifs
