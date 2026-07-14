"""#395 / M-19 — LE 7e CABLAGE MORT : les garde-fous anti-overfit n'etaient branches NULLE PART.

SEPT fonctions, toutes marquees « completed », toutes avec **ZERO appelant de production** :
`deflated_sharpe`, `whites_reality_check`, `probability_of_backtest_overfitting`,
`purged_walk_forward_splits`, `combinatorial_purged_splits`, `min_track_record_length`,
`probabilistic_sharpe_ratio`.

🔴 **Et on a lance une recherche sur 150 MILLIONS de scenarios.**

Le critere `robust` etait : `net>0 train ET net>0 test ET gate ET plateau`. **Rien ne corrigeait
la MULTIPLICITE.** Or c'est LE probleme d'une recherche massive : *le meilleur d'un tres grand
nombre de tirages a l'air genial MEME SI TOUT EST DU BRUIT.*

H-181 avait trouve le symptome (« on selectionne les 40 plus CHANCEUSES ») **sans voir que le
garde-fou cense l'attraper etait mort**.

Aucun ordre reel.
"""
from __future__ import annotations

import ast
import random
from pathlib import Path

import pytest

from hl_observer.backtesting.anti_overfit_gate import (
    MIN_TRADES,
    MOTIF_ESSAIS_INCONNUS,
    MOTIF_NOISE,
    MOTIF_OK,
    MOTIF_TROP_PEU_DE_TRADES,
    evaluer,
    sharpe,
)

RACINE = Path(__file__).resolve().parents[1]
SEARCH = RACINE / "src" / "hl_observer" / "backtesting" / "scenario_search.py"


# ============================================================ 1. 🔴 LE TEST QUI COMPTE


def test_le_MEILLEUR_de_150_MILLIONS_de_tirages_de_BRUIT_PUR_est_REFUSE():
    """🔴🔴🔴 LE TEST QUI JUSTIFIE TOUT LE MODULE.

    On tire des strategies de **BRUIT PUR** (esperance nulle, aucun edge). On garde **la
    meilleure**. Son Sharpe brut est **magnifique** -- c'est mecanique : le maximum d'un grand
    nombre de tirages est toujours grand.

    Le gate doit la **REFUSER**, parce qu'il sait contre combien de concurrents elle a gagne.

    *Sans ce gate, `scenario_search` aurait pu couronner un fantome -- et on l'aurait cru,
    puisqu'il passait le train, le test, le gate et le plateau.*
    """
    rng = random.Random(20260713)
    n_essais = 2000                      # on ne peut pas en simuler 150 M, mais l'effet est le meme
    meilleur: list[float] = []
    meilleur_sr = -9e9
    for _ in range(n_essais):
        pnls = [rng.gauss(0.0, 1.0) for _ in range(60)]     # BRUIT PUR : esperance ZERO
        sr = sharpe(pnls)
        if sr > meilleur_sr:
            meilleur_sr, meilleur = sr, pnls

    # le vainqueur a l'air excellent...
    assert meilleur_sr > 0.35, "le decor du test est faux : le meilleur devrait paraitre bon"

    # ... et pourtant il est REFUSE, parce qu'on sait qu'il a gagne contre 2 000 concurrents.
    v = evaluer(meilleur, n_essais=n_essais)
    assert v.survit is False, (
        "un vainqueur tire du BRUIT PUR (Sharpe brut %.3f, choisi parmi %d essais) a ete "
        "DECLARE ROBUSTE. Le garde-fou ne garde rien." % (meilleur_sr, n_essais)
    )
    assert v.motif == MOTIF_NOISE


def test_le_MEME_sharpe_passe_s_il_n_y_a_eu_QU_UN_SEUL_essai():
    """🚩 Le garde-fou doit pouvoir dire OUI. Sinon il refuse par principe -- il ne mesure rien.

    **C'est le cœur de l'idee** : ce n'est pas le Sharpe qui change, c'est **le nombre d'essais**.
    Un Sharpe de 0,5 obtenu du **premier coup** est credible. Le MEME Sharpe, choisi comme meilleur
    de 150 millions d'essais, ne vaut rien.

    *Le merite d'un vainqueur depend de la taille de la course.*

    🚩 MA 1re VERSION DE CE TEST ETAIT FAUSSE -- et c'est instructif. J'avais pris un edge de
    Sharpe **0,456** sur 400 trades : t-stat **9,1**. Or 150 M d'essais n'exigent que ~5,7 sigma.
    **Il survivait -- legitimement.** La deflation faisait son travail ; c'est ma mise en scene
    qui etait fausse. *Le code avait raison, le test avait tort.*

    On prend donc un edge **modeste** (t ~ 3) : credible seul, **noye** dans la multiplicite.
    C'est exactement le cas qui compte -- celui ou l'on se serait fait avoir.
    """
    rng = random.Random(7)
    pnls = [rng.gauss(0.15, 1.0) for _ in range(400)]      # edge MODESTE : t-stat ~ 3
    seul = evaluer(pnls, n_essais=1)
    foule = evaluer(pnls, n_essais=150_000_000)
    assert seul.sharpe_brut == pytest.approx(foule.sharpe_brut)   # MEME Sharpe...
    assert seul.survit is True, "un edge reel, trouve du 1er coup, doit passer"
    assert foule.survit is False, (
        "le MEME Sharpe, choisi parmi 150 millions d'essais, a ete accepte : la multiplicite "
        "n'est pas corrigee"
    )
    assert seul.proba_deflatee > foule.proba_deflatee


# ============================================================ 2. DENY-BY-DEFAULT


def test_un_nombre_d_essais_INCONNU_fait_REFUSER():
    """*Un vainqueur sans course n'est pas un champion.* Si on ignore contre combien de
    concurrents ce scenario a gagne, on **ne peut pas** juger son merite."""
    for n in (0, -1):
        v = evaluer([1.0] * 100, n_essais=n)
        assert v.survit is False
        assert v.motif == MOTIF_ESSAIS_INCONNUS


def test_trop_peu_de_trades_fait_REFUSER():
    v = evaluer([1.0, -0.5, 0.7] * 3, n_essais=10)          # 9 trades
    assert v.survit is False
    assert v.motif == MOTIF_TROP_PEU_DE_TRADES
    assert v.n_trades < MIN_TRADES


def test_un_sharpe_solide_sur_beaucoup_de_trades_et_peu_d_essais_SURVIT():
    rng = random.Random(11)
    pnls = [rng.gauss(0.8, 1.0) for _ in range(500)]
    v = evaluer(pnls, n_essais=50)
    assert v.survit is True
    assert v.motif == MOTIF_OK


# ============================================================ 3. L'INVARIANT DE CABLAGE


def test_le_gate_est_REELLEMENT_APPELE_par_scenario_search_pas_seulement_importe():
    """*Un import n'est pas un appel.* C'est TOUTE la lecon de ce projet : sept garde-fous
    anti-overfit existaient, testes, documentes -- et **aucun n'etait appele**.

    (AST, pas un grep : un grep compterait le commentaire qui explique le garde-fou.)
    """
    arbre = ast.parse(SEARCH.read_text(encoding="utf-8"))
    appels = {
        (n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", ""))
        for n in ast.walk(arbre) if isinstance(n, ast.Call)
    }
    assert "_anti_overfit" in appels, (
        "🔴 le gate anti-overfit n'est plus APPELE par scenario_search. On peut de nouveau "
        "couronner le meilleur de 150 millions de tirages de bruit."
    )


def test_les_DEUX_chemins_de_recherche_sont_gardes():
    """`search()` ET `search_over_db()`. Une porte fermee et l'autre ouverte, c'est une porte
    ouverte. (Le poller L2 : « une jambe reparee, l'autre laissee ».)"""
    src = SEARCH.read_text(encoding="utf-8")
    assert src.count("_anti_overfit(") >= 2, (
        "un seul des deux chemins de recherche est garde : l'autre peut encore couronner un "
        "fantome"
    )
    # ... et le chemin DB doit deflater par le VRAI nombre d'essais, pas par la taille du tas.
    assert "n_essais=int(evaluated)" in src, (
        "le chemin DB deflate par `len(scored)` (la taille du TAS) au lieu de `evaluated` (les "
        "150 M reellement balayes) : le garde-fou serait ridiculement indulgent -- et il aurait "
        "l'air de marcher"
    )
