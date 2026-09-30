"""#242 / IDEA-85 — la cointegration, MESUREE. Et le detecteur doit MORDRE.

« Un garde-fou qui ne peut pas echouer ne garde rien. » On verifie donc les DEUX sens :
  * sur une paire VRAIMENT cointegree (construite exprès) -> l'ADF doit crier ;
  * sur DEUX MARCHES ALEATOIRES independantes -> il doit se taire. C'est le test qui compte :
    un detecteur de cointegration qui voit de la cointegration dans du bruit fabriquerait
    des alphas fantomes -- ce projet en a deja produit 300.

Aucun ordre reel.
"""
from __future__ import annotations

import random

import pytest

from hl_observer.backtesting.cointegration_measure import (
    ADF_SEUIL_5PCT,
    MIN_POINTS_COMMUNS,
    MOTIF_INSUFFISANT,
    MOTIF_NON_COINTEGRE,
    adf_tstat,
    apparier,
    evaluer_paire,
    hedge_ratio,
    resampler,
    spread,
)


def _marche_aleatoire(n: int, *, seed: int, depart: float = 100.0, sigma: float = 0.5):
    r = random.Random(seed)
    p = depart
    out = []
    for _ in range(n):
        p = max(1e-6, p + r.gauss(0, sigma))
        out.append(p)
    return out


def _paire_cointegree(n: int, *, seed: int, beta: float = 2.0):
    """b = beta*a + bruit STATIONNAIRE. Par construction, le spread revient."""
    r = random.Random(seed)
    a = _marche_aleatoire(n, seed=seed)
    bruit = 0.0
    b = []
    for x in a:
        bruit = 0.7 * bruit + r.gauss(0, 1.0)      # AR(1) -> stationnaire
        b.append(beta * x + bruit)
    return a, b


# ============================================================ appariement


def test_le_resampling_apparie_par_le_TEMPS_pas_par_la_LIGNE():
    """⚠️ LE BUG SILENCIEUX QU'ON EVITE : deux coins n'ont pas de relevés aux memes instants.
    Les apparier ligne a ligne comparerait BTC a 10:00:03 avec ETH a 10:07:41 -- sans jamais
    lever d'erreur. *Le pire bug est celui qui ne plante pas.*"""
    a = resampler([(0.0, 10.0), (30.0, 11.0), (61.0, 12.0)], pas_s=60.0)
    b = resampler([(5.0, 100.0), (65.0, 101.0), (200.0, 999.0)], pas_s=60.0)
    xa, yb = apparier(a, b)
    assert xa == [11.0, 12.0]        # bucket 0 (dernier prix) et bucket 1
    assert yb == [100.0, 101.0]      # le bucket 3 (t=200) de b n'a pas d'equivalent : ecarte


def test_un_prix_negatif_ou_nul_est_JETE_pas_utilise():
    assert resampler([(0.0, -5.0), (1.0, 0.0), (2.0, 7.0)], pas_s=60.0) == {0: 7.0}


# ============================================================ ADF : les DEUX sens


def test_l_ADF_DETECTE_un_spread_stationnaire():
    a, b = _paire_cointegree(600, seed=1)
    alpha, beta = hedge_ratio(a, b)
    s = spread(a, b, alpha=alpha, beta=beta)
    t = adf_tstat(s)
    assert t <= ADF_SEUIL_5PCT, "ADF t=%.2f : le detecteur ne voit pas une cointegration " \
                                "CONSTRUITE. Il ne garde rien." % t
    assert beta == pytest.approx(2.0, abs=0.15)


def test_l_ADF_NE_VOIT_PAS_de_cointegration_dans_du_BRUIT_PUR():
    """🔴 LE TEST QUI COMPTE VRAIMENT.

    Deux marches aleatoires INDEPENDANTES n'ont aucune relation. Un detecteur qui y voit une
    cointegration fabriquerait des alphas fantomes -- ce projet en a deja produit 300 (purge Q3).
    On l'exige sur PLUSIEURS graines : un seul essai chanceux ne prouve rien.
    """
    faux_positifs = 0
    for seed in range(30):
        a = _marche_aleatoire(400, seed=seed)
        b = _marche_aleatoire(400, seed=1000 + seed)
        alpha, beta = hedge_ratio(a, b)
        if adf_tstat(spread(a, b, alpha=alpha, beta=beta)) <= ADF_SEUIL_5PCT:
            faux_positifs += 1
    # un test a 5 % accepte ~5 % de faux positifs ; au-dela, le detecteur ment.
    assert faux_positifs <= 4, (
        "%d/30 faux positifs sur du BRUIT PUR : ce detecteur fabriquerait des alphas fantomes"
        % faux_positifs
    )


# ============================================================ le verdict


def test_donnees_insuffisantes_INSUFFICIENT_DATA_jamais_un_chiffre_invente():
    r = evaluer_paire("A", "B", [1.0] * 50, [2.0] * 50)
    assert r.motif == MOTIF_INSUFFISANT
    assert r.viable is False
    assert r.edge_net_bps == 0.0
    assert r.n_communs < MIN_POINTS_COMMUNS


def test_deux_marches_aleatoires_sont_REFUSEES():
    a = _marche_aleatoire(600, seed=7)
    b = _marche_aleatoire(600, seed=8)
    r = evaluer_paire("A", "B", a, b)
    assert r.viable is False
    assert r.motif in (MOTIF_NON_COINTEGRE, "EDGE_NET_NEGATIF_APRES_COUTS",
                       "AUCUN_TRADE_DECLENCHE_SUR_LE_TEST")


def test_le_beta_et_les_seuils_viennent_du_TRAIN_SEUL():
    """🔴 LE LOOKAHEAD QU'ON A DEJA PAYE QUATRE FOIS. Si on estimait beta sur TOUT l'echantillon,
    le backtest connaitrait le futur. On verifie que le beta rendu est celui du TRAIN : il doit
    donc CHANGER si on change la 2e moitie... et NE PAS changer si on ne touche qu'elle."""
    a, b = _paire_cointegree(800, seed=3)
    r1 = evaluer_paire("A", "B", a, b)
    b2 = list(b[:400]) + [v * 3.0 for v in b[400:]]        # on saccage UNIQUEMENT le futur
    r2 = evaluer_paire("A", "B", a, b2)
    assert r1.beta == pytest.approx(r2.beta), (
        "le beta a bouge alors qu'on n'a modifie que le FUTUR : il est estime sur tout "
        "l'echantillon -> LOOKAHEAD."
    )


def test_les_couts_ne_peuvent_PAS_ameliorer_l_edge():
    a, b = _paire_cointegree(800, seed=5)
    cher = evaluer_paire("A", "B", a, b, cout_aller_retour_bps=50.0)
    gratuit = evaluer_paire("A", "B", a, b, cout_aller_retour_bps=0.0)
    if cher.n_trades and gratuit.n_trades:
        assert cher.edge_net_bps < gratuit.edge_net_bps
        assert gratuit.edge_brut_bps == pytest.approx(cher.edge_brut_bps)


def test_UN_SEUL_TRADE_ne_peut_JAMAIS_etre_declare_VIABLE():
    """🔴 LE CORRECTIF QUE MA PROPRE 1re EXECUTION A EXIGE (2026-07-13).

    Ma 1re passe sur les donnees reelles a imprime **« VIABLE : +95,29 bps »** sur SOL/HYPE...
    avec **UN SEUL TRADE** hors echantillon. Un edge moyen calcule sur un trade n'est pas une
    mesure : **c'est une anecdote**. Et j'avais ecrit « un seul essai chanceux ne prouve rien »
    dans mes propres tests, trois heures plus tot.

    *Suspecter son PROPRE outil avant le code d'autrui.*
    """
    from hl_observer.backtesting.cointegration_measure import (
        MIN_TRADES_OOS,
        MOTIF_TROP_PEU_DE_TRADES,
    )
    a, b = _paire_cointegree(900, seed=11)
    # un seuil d'entree ENORME -> presque aucun trade ne se declenche
    r = evaluer_paire("A", "B", a, b, entree_z=6.0, sortie_z=0.1)
    if 0 < r.n_trades < MIN_TRADES_OOS:
        assert r.viable is False, (
            "%d trade(s) et pourtant declare VIABLE : c'est une anecdote presentee comme une "
            "mesure." % r.n_trades
        )
        assert r.motif == MOTIF_TROP_PEU_DE_TRADES


def test_le_cout_par_defaut_compte_QUATRE_executions_pas_deux():
    """Un pairs trade ouvre DEUX jambes et les ferme : 4 executions. Un defaut a 3 bps
    (= une seule jambe, aller simple) rendrait tout viable sur le papier."""
    from hl_observer.backtesting import cointegration_measure as cm
    import inspect
    sig = inspect.signature(cm.evaluer_paire)
    defaut = sig.parameters["cout_aller_retour_bps"].default
    assert defaut >= 10.0, (
        "cout par defaut = %.1f bps : trop bas pour 4 executions. Ce serait un edge fabrique."
        % defaut
    )
