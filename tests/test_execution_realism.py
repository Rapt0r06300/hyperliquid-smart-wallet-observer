"""#576 + #496 + #498 + #540 + #572 -- **notre PnL simule est-il PHYSIQUEMENT REALISABLE ?**

Un trade qui aurait ete REJETE par l'exchange et qu'on compte quand meme est un trade **INVENTE**.
Un stop resolu dans le mauvais sens a l'interieur d'une bougie est un gain **FABRIQUE**.
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting.intrabar import (
    AUCUN,
    HONNETE,
    INDETERMINE,
    OPTIMISTE,
    PESSIMISTE,
    SL,
    TP,
    Bougie,
    compter_ambiguites,
    ecart_optimiste_pessimiste,
    resoudre_bougie,
)
from hl_observer.market.execution_constraints import (
    CHIFFRES_SIGNIFICATIFS_MAX,
    MOTIF_NOTIONNEL_TROP_PETIT,
    MOTIF_OK,
    MOTIF_POST_ONLY_AURAIT_CROISE,
    MOTIF_TAILLE_NULLE_APRES_ARRONDI,
    NOTIONNEL_MIN_USD,
    NOTRE_NOTIONNEL_USD,
    REJETS_OFFICIELS,
    arrondir_prix,
    arrondir_taille,
    notre_sizing_passe_le_minimum,
    valider_ordre,
)


# ════════════════════════════════════════════════════════════════════════════════════════════
# #576 — LES CONTRAINTES, CITEES DE LA DOC
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_notionnel_minimum_est_10_dollars_et_NE_NOUS_MORD_PAS() -> None:
    """Doc : « MinTradeNtl : Order must have minimum value of $10. »

    ✅ On size a **500 $** (marge 50 $ x levier 10). **Constate, pas suppose.**
    """
    assert NOTIONNEL_MIN_USD == 10.0
    assert NOTRE_NOTIONNEL_USD == 500.0
    assert notre_sizing_passe_le_minimum()


def test_un_ordre_sous_10_dollars_est_REJETE() -> None:
    v = valider_ordre(prix=100.0, taille=0.05, sz_decimals=3)     # 5 $ de notionnel
    assert not v.valide and v.motif == MOTIF_NOTIONNEL_TROP_PETIT
    assert "10" in v.detail


def test_les_prix_de_la_DOC_sont_reproduits_exactement() -> None:
    """Doc : « `1234.5` is valid but `1234.56` is not (too many significant figures) »."""
    assert arrondir_prix(1234.56, sz_decimals=0) == pytest.approx(1234.6)   # -> 5 sig
    assert arrondir_prix(1234.5, sz_decimals=0) == pytest.approx(1234.5)    # deja valide
    assert CHIFFRES_SIGNIFICATIFS_MAX == 5


def test_un_prix_ENTIER_est_toujours_valide_meme_a_6_chiffres() -> None:
    """Doc : « Integer prices are always allowed, regardless of the number of significant figures.

    E.g. `123456` is a valid price even though `12345.6` is not. »
    """
    assert arrondir_prix(123456.0, sz_decimals=0) == pytest.approx(123456.0)
    # 12345.6 a 6 chiffres significatifs -> doit etre ramene a l'entier
    assert arrondir_prix(12345.6, sz_decimals=0) == pytest.approx(12346.0)


def test_la_limite_de_decimales_depend_de_szDecimals() -> None:
    """Doc : « no more than MAX_DECIMALS - szDecimals decimal places », 6 pour les perps."""
    # szDecimals=1 -> au plus 5 decimales. `0.01234` valide, `0.012345` non.
    assert arrondir_prix(0.01234, sz_decimals=1) == pytest.approx(0.01234)
    assert arrondir_prix(0.012345, sz_decimals=1) == pytest.approx(0.01234, abs=1e-6)


def test_la_taille_est_arrondie_VERS_LE_BAS() -> None:
    """⚠️ Vers le BAS : une simulation qui arrondit vers le haut s'offre de la taille gratuite."""
    assert arrondir_taille(1.0009, sz_decimals=3) == pytest.approx(1.000)
    assert arrondir_taille(1.9999, sz_decimals=0) == pytest.approx(1.0)


def test_une_taille_ECRASEE_A_ZERO_par_szDecimals_ANNULE_le_trade() -> None:
    """🔴 Si szDecimals=0 et qu'on voulait 0,4 unite -> **0**. Le trade n'existe pas."""
    v = valider_ordre(prix=50000.0, taille=0.4, sz_decimals=0)
    assert not v.valide and v.motif == MOTIF_TAILLE_NULLE_APRES_ARRONDI
    assert "n'existe pas" in v.detail


def test_un_ordre_normal_passe() -> None:
    v = valider_ordre(prix=3456.7, taille=0.145, sz_decimals=3)   # ~501 $
    assert v.valide and v.motif == MOTIF_OK
    assert v.taille_arrondie == pytest.approx(0.145)


# ════════════════════════════════════════════════════════════════════════════════════════════
# #498 + #540 — `BadAloPx` : LE POST-ONLY QUI CROISE EST **REJETE**, PAS EXECUTE EN TAKER
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_un_post_only_qui_CROISERAIT_est_REJETE_pas_converti_en_taker() -> None:
    """🔴 Doc : « BadAloPx : Post only order would have immediately matched. »

    ***Une simulation qui compte un fill ici INVENTE un trade.***
    Et si elle le compte au tarif maker alors qu'il aurait ete taker, elle se trompe d'un
    **facteur 3** (1,5 bps contre 4,5).
    """
    # on ACHETE a 100 alors que le meilleur ASK est a 99 -> on croiserait
    v = valider_ordre(prix=100.0, taille=10.0, sz_decimals=2,
                      post_only=True, meilleur_oppose=99.0, achat=True)
    assert not v.valide and v.motif == MOTIF_POST_ONLY_AURAIT_CROISE
    assert "PAS execute en taker" in v.detail


def test_un_post_only_qui_ne_croise_PAS_passe() -> None:
    v = valider_ordre(prix=98.0, taille=10.0, sz_decimals=2,
                      post_only=True, meilleur_oppose=99.0, achat=True)
    assert v.valide


def test_le_meme_test_en_VENTE() -> None:
    # on VEND a 98 alors que le meilleur BID est a 99 -> on croiserait
    v = valider_ordre(prix=98.0, taille=10.0, sz_decimals=2,
                      post_only=True, meilleur_oppose=99.0, achat=False)
    assert not v.valide and v.motif == MOTIF_POST_ONLY_AURAIT_CROISE


# ════════════════════════════════════════════════════════════════════════════════════════════
# #496 — LA LISTE DES REJETS : celle de la DOC, aucune inventee
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_la_liste_des_rejets_vient_de_la_doc() -> None:
    for attendu in ("Tick", "MinTradeNtl", "BadAloPx", "Oracle", "MarketOrderNoLiquidity",
                    "PerpMargin", "OpenInterestIncrease"):
        assert attendu in REJETS_OFFICIELS
    assert "Oracle" in REJETS_OFFICIELS, (
        "🔴 « Order price too far from oracle » : on ne peut PAS coter arbitrairement loin. "
        "Un backtest qui le fait fabrique des fills impossibles."
    )


# ════════════════════════════════════════════════════════════════════════════════════════════
# #572 — LE PROBLEME INTRA-BOUGIE
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_une_bougie_qui_touche_LES_DEUX_est_INDETERMINEE() -> None:
    """🔴 LE CŒUR DU PROBLEME. La bougie ne dit pas dans quel ordre high et low sont venus."""
    b = Bougie(open=100.0, high=110.0, low=90.0, close=105.0)
    r = resoudre_bougie(b, sl=95.0, tp=108.0, long=True, mode=HONNETE)
    assert r.issue == INDETERMINE and r.ambigu
    assert "DANS_QUEL_ORDRE" in r.motif


def test_le_mode_par_defaut_est_PESSIMISTE_on_ne_se_fait_PAS_de_cadeau() -> None:
    b = Bougie(open=100.0, high=110.0, low=90.0, close=105.0)
    assert resoudre_bougie(b, sl=95.0, tp=108.0).issue == SL          # defaut = PESSIMISTE
    assert resoudre_bougie(b, sl=95.0, tp=108.0, mode=OPTIMISTE).issue == TP
    assert PESSIMISTE != OPTIMISTE


def test_les_cas_NON_ambigus_sont_tranches_sans_hesiter() -> None:
    b = Bougie(open=100.0, high=110.0, low=99.0, close=105.0)
    assert resoudre_bougie(b, sl=95.0, tp=108.0).issue == TP          # le SL n'est pas touche
    assert not resoudre_bougie(b, sl=95.0, tp=108.0).ambigu
    assert resoudre_bougie(b, sl=95.0, tp=120.0).issue == AUCUN       # ni l'un ni l'autre


def test_une_bougie_INCOHERENTE_est_ECARTEE_jamais_devinee() -> None:
    assert resoudre_bougie(Bougie(100.0, 90.0, 110.0, 105.0), sl=95.0, tp=108.0).issue == AUCUN


def test_on_COMPTE_les_ambiguites_c_est_le_chiffre_qui_juge_la_mesure() -> None:
    bougies = [Bougie(100.0, 110.0, 90.0, 105.0)] * 3 + [Bougie(100.0, 101.0, 99.0, 100.0)] * 7
    c = compter_ambiguites(bougies, sl=95.0, tp=108.0)
    assert c["n_bougies"] == 10 and c["n_ambigues"] == 3
    assert c["part_ambigue"] == pytest.approx(0.30)
    assert "SUSPECTE" in c["avertissement"]


def test_l_ecart_optimiste_pessimiste_MESURE_le_mensonge_possible() -> None:
    """**Le meme backtest, deux hypotheses, deux resultats.** Si l'ecart est gros, rien ne vaut."""
    bougies = [Bougie(100.0, 110.0, 90.0, 105.0)] * 5
    e = ecart_optimiste_pessimiste(bougies, sl=95.0, tp=108.0)
    assert e["tp_si_optimiste"] == 5 and e["tp_si_pessimiste"] == 0
    assert e["trades_qui_changent_d_issue"] == 5, (
        "**5 trades sur 5 changent d'issue selon l'hypothese.** Aucun des deux backtests n'est vrai."
    )


def test_le_SHORT_est_traite_symetriquement() -> None:
    b = Bougie(open=100.0, high=110.0, low=90.0, close=95.0)
    # short : SL au-dessus (105), TP en dessous (92) -> les deux touches
    r = resoudre_bougie(b, sl=105.0, tp=92.0, long=False, mode=HONNETE)
    assert r.issue == INDETERMINE and r.ambigu
