"""#549 / H-144 -- lead-lag BTC -> alts. **La niche vide, et POURQUOI elle est vide.**

🔴 LE GARDE CENTRAL : `test_une_CORRELATION_CONTEMPORAINE_n_est_PAS_un_lead_lag`.

Mesure reelle (208 j, 12 coins, 66 tests) : **0 viable**.
BNB : corr(lag 0) = **+0,83** ; corr(lag 2 h) = **-0,03**.
***BTC et les alts bougent ENSEMBLE. Les alts ne SUIVENT pas.***
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting.lead_lag import (
    COUT_ALLER_RETOUR_BPS,
    MOTIF_EDGE_SOUS_LES_COUTS,
    MOTIF_PAS_ASSEZ_DE_POINTS,
    MOTIF_PAS_DE_LEAD_LAG,
    correlation,
    evaluer,
    rendements,
    resume,
)


def test_les_couts_viennent_de_la_source_unique() -> None:
    assert COUT_ALLER_RETOUR_BPS == pytest.approx(9.0)      # 2 x 4,5 bps taker


def test_les_rendements_ne_fabriquent_pas_de_prix() -> None:
    assert rendements([100.0, 110.0]) == [pytest.approx(0.10)]
    assert rendements([100.0, 0.0, 50.0]) == [0.0, 0.0]     # prix absurde -> 0, jamais devine
    assert rendements([100.0]) == []


def test_une_CORRELATION_CONTEMPORAINE_n_est_PAS_un_lead_lag() -> None:
    """🔴🔴 **LE GARDE CENTRAL — et le bug que je m'attendais a faire.**

    Deux series qui bougent ENSEMBLE ont une corr(0) enorme. Si on ne compare pas au lag 0,
    on prend cette correlation pour un lead-lag. **C'est exactement le cas de BNB : +0,83.**

    *Et une correlation contemporaine ne se trade pas : quand BTC a bouge, l'alt a DEJA bouge.*
    """
    import random
    random.seed(7)
    btc = [random.gauss(0, 0.01) for _ in range(400)]
    alt = [x + random.gauss(0, 0.001) for x in btc]         # bouge EN MEME TEMPS que BTC

    assert correlation(btc, alt) > 0.9                       # corr(0) tres elevee
    r = evaluer("ALT", btc, alt, lag_h=1)
    assert not r.viable
    assert r.motif == MOTIF_PAS_DE_LEAD_LAG
    assert abs(r.corr_lag) <= abs(r.corr_lag0)
    assert "bougent ENSEMBLE" in r.note


def test_un_VRAI_lead_lag_est_reconnu() -> None:
    """Le controle positif : si l'alt SUIT vraiment BTC avec 1 h de retard, on le voit."""
    import random
    random.seed(11)
    btc = [random.gauss(0, 0.02) for _ in range(400)]
    alt = [0.0] + [x * 0.9 + random.gauss(0, 0.002) for x in btc]   # decale de 1

    r = evaluer("ALT", btc, alt, lag_h=1)
    assert abs(r.corr_lag) > abs(r.corr_lag0), "le lag 1 doit battre le lag 0"
    assert r.motif != MOTIF_PAS_DE_LEAD_LAG
    assert r.edge_brut_bps > 0.0


def test_un_signal_reel_mais_TROP_PETIT_est_refuse() -> None:
    """*Le signal existe peut-etre ; il ne paie pas.* C'est le cas de nos 66 tests."""
    import random
    random.seed(3)
    btc = [random.gauss(0, 0.0002) for _ in range(400)]      # vol minuscule
    alt = [0.0] + [x * 0.9 + random.gauss(0, 0.00002) for x in btc]
    r = evaluer("ALT", btc, alt, lag_h=1)
    assert not r.viable
    assert r.motif == MOTIF_EDGE_SOUS_LES_COUTS
    assert r.edge_net_bps < 0.0


def test_un_lag_zero_est_INTERDIT() -> None:
    """k=0 serait la correlation contemporaine -- justement ce qu'on refuse d'appeler lead-lag."""
    with pytest.raises(ValueError):
        evaluer("ALT", [0.1] * 300, [0.1] * 300, lag_h=0)


def test_un_echantillon_court_ne_donne_AUCUN_chiffre() -> None:
    r = evaluer("ALT", [0.01] * 50, [0.01] * 50, lag_h=1)
    assert not r.viable and MOTIF_PAS_ASSEZ_DE_POINTS in r.motif


def test_le_resume_declare_la_MULTIPLICITE_pour_l_anti_overfit() -> None:
    """12 coins x 6 lags = 66 tests. **Le meilleur de 66 a l'air genial meme si tout est du bruit.**"""
    rs = [evaluer("A", [0.01] * 300, [0.01] * 300, lag_h=k) for k in (1, 2, 3)]
    r = resume(rs)
    assert r["n_essais_pour_l_anti_overfit"] == 3
    assert r["n_viables"] == 0
    # le module DECLARE son attente d'echec AVANT de mesurer -- pour ne pas pouvoir
    # se raconter une histoire apres coup
    a = r["attente_declaree_AVANT"]
    assert "NE RIEN TROUVER" in a and "bug" in a
    assert r["real_execution"] is False
