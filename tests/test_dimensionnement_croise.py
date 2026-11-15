"""Le plafond de levier etait faux d'un facteur 20.

`survie_position` plafonnait a 0,235x en exigeant qu'une JAMBE NUE survive a +400 % d'excursion —
un chiffre venu d'une etude de cash-and-carry ou le short etait COUVERT PAR UN LONG SPOT. Applique
a un livre long/short dollar-neutre en MARGE CROISEE, c'est une contrainte de marge isolee sur un
livre couvert.

La venue, mot pour mot : « Cross positions are liquidated when **the account value (including
unrealized pnl)** is less than the maintenance margin times the total open notional position. »
Et la nuance qui empeche de sur-corriger : « Cross margin lets profits offset losses. It does not
necessarily reduce what a hedged book must post. Standard margin sums position-level requirements
and gives no hedge benefit. »

D'ou : `maintenance = SOMME(notionnel_i * mmr_i)` sans remise, et `valeur = capital + SOMME(PnL)`
avec compensation. Soit `N < C / (D + mmr)`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import dimensionnement_croise as D  # noqa: E402
from hl_observer.backtesting import survie_position as S  # noqa: E402


# ------------------------------------------------------- le mmr du livre

def test_c_est_le_palier_le_PLUS_CONTRAIGNANT_qui_decide_pas_la_moyenne():
    """La maintenance est une SOMME sans remise de couverture. Moyenner un actif a 5 % avec un
    actif a 1,25 % sous-estimerait ce que le livre doit poster — et le sous-dimensionnement de
    marge est precisement ce qui liquide."""
    taux = [S.taux_de_maintenance(40), S.taux_de_maintenance(10)]   # 1,25 % et 5 %
    assert D.mmr_du_livre(taux) == 0.05
    assert D.mmr_du_livre([]) is None


# ------------------------------------------------------- la formule

def test_la_formule_reproduit_le_facteur_20_par_rapport_a_la_jambe_nue():
    """Le coeur du correctif. Sur le repli reellement observe du livre (15,89 % en 30 j) et un
    mmr de 5 %, la marge croisee autorise ~4,8x la ou la jambe nue imposait 0,235x."""
    r = D.notionnel_maximum(capital_usd=350.0, repli=0.1589, taux_maintenance=0.05,
                            facteur_de_securite=1.0)
    assert r["verdict"] == D.MESURE
    assert abs(r["levier"] - 1 / 0.2089) < 0.02
    ancien = S.levier_maximum_survivable(excursion=4.00,
                                         taux_maintenance=S.taux_de_maintenance(10))
    assert r["levier"] / ancien > 15          # l'ordre de grandeur de l'erreur corrigee


def test_le_facteur_de_securite_reduit_bien_le_levier():
    base = D.notionnel_maximum(capital_usd=350.0, repli=0.1589, taux_maintenance=0.05,
                               facteur_de_securite=1.0)["levier"]
    triple = D.notionnel_maximum(capital_usd=350.0, repli=0.1589, taux_maintenance=0.05,
                                 facteur_de_securite=3.0)["levier"]
    assert triple < base / 2
    assert abs(triple - 1 / (3 * 0.1589 + 0.05)) < 0.01


def test_le_repli_qui_liquide_est_PUBLIE():
    """L'operateur doit voir de combien le livre peut perdre avant la liquidation, pas seulement
    le levier autorise."""
    r = D.notionnel_maximum(capital_usd=350.0, repli=0.10, taux_maintenance=0.05,
                            facteur_de_securite=2.0)
    assert abs(r["repli_qui_liquide"] - 0.25) < 1e-9     # 2 x 10 % + 5 %
    assert "liquide si le livre perd" in r["lecture"]


# ------------------------------------------------------- les refus

def test_un_facteur_de_securite_ABSENT_est_refuse():
    """Dimensionner sur le pire repli OBSERVE garantit une liquidation au premier evenement pire.
    Ce module refuse de choisir ce facteur a la place de l'operateur."""
    r = D.notionnel_maximum(capital_usd=350.0, repli=0.1589, taux_maintenance=0.05,
                            facteur_de_securite=None)
    assert r["verdict"] == D.NON_MESURABLE
    assert r["motif"] == D.FACTEUR_ABSENT
    assert "refuse de choisir" in r["lecture"]


def test_un_facteur_SOUS_UN_est_refuse():
    r = D.notionnel_maximum(capital_usd=350.0, repli=0.1589, taux_maintenance=0.05,
                            facteur_de_securite=0.5)
    assert r["verdict"] == D.NON_MESURABLE


def test_un_repli_ABSENT_ne_donne_PAS_un_levier_infini():
    for mauvais in (None, 0.0, -0.1):
        r = D.notionnel_maximum(capital_usd=350.0, repli=mauvais, taux_maintenance=0.05,
                                facteur_de_securite=2.0)
        assert r["verdict"] == D.NON_MESURABLE
        assert r["motif"] == D.REPLI_ABSENT


def test_un_capital_invalide_est_refuse():
    r = D.notionnel_maximum(capital_usd=0.0, repli=0.1, taux_maintenance=0.05,
                            facteur_de_securite=2.0)
    assert r["verdict"] == D.NON_MESURABLE
    assert r["motif"] == D.CAPITAL_INVALIDE


# ------------------------------------------------------- le plan

def test_le_plan_publie_l_eventail_sans_elire_de_facteur():
    """Le choix du facteur est un choix de RISQUE. Le publier en eventail laisse la decision ou
    elle doit etre, et montre ce que chaque cran coute en rendement."""
    p = D.plan(capital_usd=350.0, repli=0.1589, taux_maintenance=0.05,
               rendement_annuel_sur_notionnel=0.413, facteurs=(1.0, 2.0, 3.0), jambes=8)
    assert len(p["lignes"]) == 3
    assert "pas une optimisation" in p["avertissement"]
    leviers = [l["levier"] for l in p["lignes"]]
    assert leviers == sorted(leviers, reverse=True)      # plus prudent => moins de levier
    # le rendement suit le levier
    for ligne in p["lignes"]:
        assert ligne["rendement_sur_capital"] > 0
        assert ligne["usd_par_an"] > 0


def test_le_plan_signale_une_jambe_sous_le_minimum_de_la_venue():
    """Un notionnel trop petit par jambe redevient un ordre rejete, quel que soit le levier."""
    p = D.plan(capital_usd=50.0, repli=0.50, taux_maintenance=0.05,
               rendement_annuel_sur_notionnel=0.4, facteurs=(3.0,), jambes=20)
    assert p["lignes"][0]["placable"] is False


# ------------------------------------------------------- LE DECOUPAGE EN TRANCHES

def test_le_decoupage_REDUIT_le_repli_sans_toucher_au_rendement_moyen():
    """Le decoupage ne change que le MOMENT de l'entree. Mesure sur 211 jours : le repli passe de
    12,19 % a 4,34 %, soit un levier de 1,86x a 4,47x et un resultat x2,4."""
    nets = [0.01, 0.01, -0.12, 0.01, 0.01, 0.01, -0.02, 0.01]
    seul = D.repli_tranche(nets, tranches=1)
    quatre = D.repli_tranche(nets, tranches=4)
    assert seul == pytest.approx(0.12)          # le pire pas isole
    assert quatre < seul / 2                     # la moyenne mobile dilue le choc


def test_PIEGE_1_le_repli_tranche_n_est_PAS_le_pire_pas_divise_par_t():
    """Les tranches peuvent perdre ENSEMBLE. Diviser par t en gardant le capital deploye
    compterait la diversification DEUX FOIS."""
    nets = [-0.12] * 8          # toutes les detentions perdent le maximum, EN MEME TEMPS
    assert D.repli_tranche(nets, tranches=4) == pytest.approx(0.12)   # et non 0,03
    assert D.repli_tranche(nets, tranches=4) != pytest.approx(0.12 / 4)


def test_PIEGE_2_un_bloc_unique_ne_CHOISIT_pas_sa_fenetre_d_entree():
    """Lire son repli sur une detention sur quatre lui laisserait choisir son moment d'entree, ce
    qu'aucun livre ne peut faire."""
    nets = [0.01, 0.01, 0.01, -0.20, 0.01, 0.01, 0.01, 0.01]
    # une lecture « une sur quatre » partant de l'indice 0 manquerait le -0,20
    assert D.repli_tranche(nets, tranches=1) == pytest.approx(0.20)


def test_un_decoupage_impossible_rend_None_et_pas_un_repli_optimiste():
    assert D.repli_tranche([0.01, 0.01], tranches=4) is None
    assert D.repli_tranche([], tranches=1) is None
    assert D.repli_tranche([0.01], tranches=0) is None


def test_le_repli_tranche_alimente_directement_le_dimensionnement():
    nets = [0.01, 0.01, -0.12, 0.01, 0.01, 0.01, -0.02, 0.01]
    for tranches in (1, 4):
        d = D.repli_tranche(nets, tranches=tranches)
        r = D.notionnel_maximum(capital_usd=350.0, repli=d, taux_maintenance=0.05,
                                facteur_de_securite=4.0)
        assert r["verdict"] == D.MESURE
    assert (D.notionnel_maximum(capital_usd=350.0, repli=D.repli_tranche(nets, tranches=4),
                                taux_maintenance=0.05, facteur_de_securite=4.0)["levier"]
            > D.notionnel_maximum(capital_usd=350.0, repli=D.repli_tranche(nets, tranches=1),
                                  taux_maintenance=0.05, facteur_de_securite=4.0)["levier"])
