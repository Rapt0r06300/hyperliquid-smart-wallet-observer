"""L'APR DOIT ETRE **NET**. *Un cout qu'on verifie mais qu'on ne soustrait pas est un cout CACHE.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LE BUG QUE CES TESTS VERROUILLENT — *la maladie du projet, 17e forme*
═══════════════════════════════════════════════════════════════════════════════════════════════

    apr_sur_capital = (funding / 2 jambes) x 24 x 365

***Les 23 bps de couts (4 executions : spot + perp, entree + sortie) n'y figuraient PAS.***

Ils etaient bien calcules. Ils etaient bien **verifies a la porte** (`heures_pour_amortir <= 720`).
Puis ils **disparaissaient** du chiffre affiche a Flo, au dashboard, aux exports.

*Une capacite presente, un chainon manquant, personne qui se plaint.* **Exactement la meme forme
que le plancher a zero** : le cout EXISTE dans le code, mais il ne descend pas dans le nombre.

Ecart mesure sur les 3 coins que le bot ouvre :

    PURR   12,71 %  ->  **11,31 %**
    PUMP    6,63 %  ->  **5,23 %**
    HYPE    5,87 %  ->  **4,48 %**

🔴 **Et ce n'est PAS cosmetique.** A 4,5 % net, HYPE et PUMP **perdent contre un depot passif
dans HLP**. Le chiffre BRUT les faisait passer pour des gagnants.

Aucun ordre reel. Paper-only.
"""
from __future__ import annotations

import pytest

from hl_observer.strategies.carry_runtime import (
    CAPITAL_SUR_DEUX_JAMBES,
    COUT_ALLER_RETOUR_MAKER_BPS,
    COUT_ALLER_RETOUR_TAKER_BPS,
    HEURES_MAX_POUR_AMORTIR,
    CandidatCarry,
    evaluer,
)

# Les 3 coins que le bot ouvre reellement, avec leur funding MESURE sur 365 jours.
PURR = 0.2902
PUMP = 0.1513
HYPE = 0.1341
MON = 0.0303          # trop faible : ne doit meme pas amortir


def _c(f: float) -> CandidatCarry:
    return CandidatCarry(coin="X", funding_bps_h=f, notional_usd=500.0)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. LE COUT DOIT ETRE **DANS** LE CHIFFRE. C'est tout le bug.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("f", [PURR, PUMP, HYPE])
def test_l_apr_net_est_STRICTEMENT_inferieur_au_brut(f: float) -> None:
    """🔑 **LE TEST QUI COMPTE.** Si net == brut, les couts ont disparu.

    C'est *exactement* ce qui se passait : la formule ne contenait pas les 23 bps.
    """
    c = _c(f)
    brut, net = c.apr_brut_sur_capital, c.apr_net_sur_capital()
    assert net < brut, (
        "REGRESSION : l'APR net (%.4f) n'est pas inferieur au brut (%.4f). "
        "Les couts (23 bps, 4 executions) ont disparu du chiffre. "
        "*Un cout qu'on verifie mais qu'on ne soustrait pas est un cout qu'on CACHE.*"
        % (net, brut)
    )


def test_l_alias_historique_pointe_sur_le_NET() -> None:
    """🔒 `apr_sur_capital` est appele par le scanner, le noyau, les exports.

    On ne le renomme pas : **on corrige sa valeur.** Sinon l'ancien chiffre faux survivrait
    quelque part -- *et c'est toujours la ou il survit qu'il finit par mentir.*
    """
    c = _c(PURR)
    assert c.apr_sur_capital == c.apr_net_sur_capital()
    assert c.apr_sur_capital != c.apr_brut_sur_capital


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2. L'ARITHMETIQUE, verifiee a la main. *On compte, on ne raconte pas.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_le_calcul_exact_sur_PURR() -> None:
    """PURR : 0,2902 bps/h.

        brut sur 30 j = 0,2902 x 720          = 208,94 bps
        net           = 208,94 - 23,0         = 185,94 bps
        par jambe     = 185,94 / 2            =  92,97 bps
        annualise     = 92,97 / 1e4 x 12,167  =  **11,31 %**
    """
    brut_h = PURR * HEURES_MAX_POUR_AMORTIR
    net_h = brut_h - COUT_ALLER_RETOUR_TAKER_BPS
    attendu = (net_h / CAPITAL_SUR_DEUX_JAMBES) / 1e4 * (24 * 365 / HEURES_MAX_POUR_AMORTIR)
    assert _c(PURR).apr_net_sur_capital() == pytest.approx(attendu, rel=1e-9)
    assert _c(PURR).apr_net_sur_capital() == pytest.approx(0.1131, abs=5e-4)


def test_le_maker_rend_plus_que_le_taker_car_il_coute_moins() -> None:
    c = _c(PURR)
    assert (c.apr_net_sur_capital(cout_bps=COUT_ALLER_RETOUR_MAKER_BPS)
            > c.apr_net_sur_capital(cout_bps=COUT_ALLER_RETOUR_TAKER_BPS))


def test_les_couts_ne_sont_JAMAIS_zero() -> None:
    """🚨 Le plancher a zero, en costume neuf. **Interdit.**"""
    assert COUT_ALLER_RETOUR_TAKER_BPS == pytest.approx(23.0)
    assert COUT_ALLER_RETOUR_MAKER_BPS == pytest.approx(11.0)
    assert COUT_ALLER_RETOUR_TAKER_BPS > 0 and COUT_ALLER_RETOUR_MAKER_BPS > 0


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  3. ON NE MAQUILLE JAMAIS UN PERDANT.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_un_funding_qui_n_amortit_pas_rend_ZERO_jamais_un_APR_positif() -> None:
    """MON : +0,0303 bps/h -> 21,8 bps sur 30 j **contre 23 bps de couts**. Il PERD.

    L'APR doit valoir **0,0** -- surtout pas un joli chiffre positif issu du brut.
    """
    c = _c(MON)
    assert c.apr_brut_sur_capital > 0            # le brut, lui, est "beau"
    assert c.apr_net_sur_capital() == 0.0, (
        "un carry qui n'amortit pas ses couts ne rend pas un APR positif : il rend ZERO"
    )
    assert not evaluer(c).ouvrable


def test_la_porte_ET_le_chiffre_disent_la_MEME_chose() -> None:
    """*Un nombre qu'on ne peut pas remonter jusqu'a un rapport finira par mentir.* (#578)

    Si `evaluer()` dit « ouvrable », l'APR net doit etre > 0. Et inversement.
    **La porte et le chiffre ne doivent JAMAIS se contredire.**
    """
    for f in (PURR, PUMP, HYPE, MON, 0.001, 0.0):
        c = _c(f)
        ouvrable = evaluer(c).ouvrable
        net = c.apr_net_sur_capital()
        assert ouvrable == (net > 0), (
            "CONTRADICTION sur funding=%s : porte=%s mais APR net=%.4f. "
            "La porte et le chiffre doivent dire la meme chose." % (f, ouvrable, net)
        )
