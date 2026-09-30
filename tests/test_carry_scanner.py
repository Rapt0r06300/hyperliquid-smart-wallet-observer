"""LE SCANNER CARRY — **le maillon qui manquait.**

🔴 Le noyau ACCEPTE la famille CARRY. Le moteur SAIT juger un carry.
   ***Mais RIEN ne PRODUISAIT de candidat carry.*** -> le bot ne pouvait ouvrir AUCUNE position.
   *Une capacite presente, un chainon manquant, personne qui se plaint.* **Encore.**

🔴 LE TEST QUI COMPTE : `test_AZTEC_le_piege_que_365_jours_a_revele`.
"""
from __future__ import annotations

import pytest

from hl_observer.strategies.carry_scanner import (
    MIN_HEURES_HISTORIQUE,
    MOTIF_FUNDING_NEGATIF,
    MOTIF_HISTORIQUE_COURT,
    MOTIF_INSTABLE,
    MOTIF_PAS_DE_SPOT,
    MOTIF_RETENU,
    PART_HEURES_POSITIVES_MIN,
    rapport,
    scanner,
)

SPOT = {"HYPE", "PURR", "PUMP", "AZTEC", "MON", "BERA", "TRUMP", "STABLE"}


def _serie(moy: float, part_pos: float, n: int = 8760, *, pos: float | None = None) -> list[float]:
    """Une serie de funding avec une moyenne ET une part d'heures positives IMPOSEES.

    ═══════════════════════════════════════════════════════════════════════════════════════════
    🔴🔴🔴 **CETTE AIDE DE TEST MENTAIT — ET ELLE A RENDU TROIS TESTS AVEUGLES.**
    ═══════════════════════════════════════════════════════════════════════════════════════════

    L'ancienne version fixait `pos = 0,30` **en dur**, puis calculait la valeur « negative »
    par difference. Quand la moyenne demandee etait **>= 0,30**, cette « negative » ressortait
    **POSITIVE** -- et la serie devenait **100 %% positive** en silence :

        `_serie(0.30, 0.50)`  -> neg = **+0,30**   (croyait 50 %% -> avait **100 %%**)
        `_serie(0.50, 0.99)`  -> neg = **+20,21**  (croyait 99 %% -> avait **100 %%**)

    *Trois tests croyaient verifier la porte de STABILITE. Ils ne verifiaient RIEN.*

    ***C'est la maladie du projet — mais DANS LES TESTS.*** Une capacite presente (l'aide),
    un chainon casse (le calcul), personne qui se plaint (les tests passaient au vert).

    ═══════════════════════════════════════════════════════════════════════════════════════════
    LA REPARATION — *l'aide CALCULE une forme valide au lieu d'en ESPERER une*
    ═══════════════════════════════════════════════════════════════════════════════════════════

    Pour que les heures « negatives » soient vraiment negatives, il faut :

        pos * n_pos  >  moy * n        <=>        **pos > moy / part_pos**

    -> `pos` est donc **DERIVE** de la demande (et non plus devine), puis l'aide **VERIFIE**
       ce qu'elle vient de fabriquer et **LEVE** si ca ne correspond pas.
       **Elle ne peut plus mentir en silence.**
    """
    n_pos = int(round(n * part_pos))
    n_neg = n - n_pos

    if n_neg == 0:
        s = [moy] * n
    else:
        if pos is None:
            # 🔑 DERIVE, jamais devine : strictement au-dessus du seuil qui rend `neg` negatif.
            #    (pour moy <= 0, n'importe quel positif convient -> on garde 0,30)
            pos = max(0.30, (moy / part_pos) * 1.5 + 0.10) if moy > 0 else 0.30
        neg = (moy * n - pos * n_pos) / n_neg
        if n_pos and neg >= 0:
            raise AssertionError(
                "_serie(%s, %s, pos=%s) : la valeur 'negative' vaut %+.4f -- elle n'est PAS "
                "negative. La serie aurait 100 %% d'heures positives, pas %.0f %%. "
                "***L'aide de test aurait menti en silence.***"
                % (moy, part_pos, pos, neg, part_pos * 100)
            )
        s = [pos] * n_pos + [neg] * n_neg

    # 🔒 DENY-BY-DEFAULT DANS L'AIDE ELLE-MEME : on verifie ce qu'on vient de fabriquer.
    #    *Un outil qu'on ne verifie pas est un outil auquel on fait confiance sans raison.*
    vraie_moy = sum(s) / len(s)
    vraie_part = sum(1 for x in s if x > 0) / len(s)
    assert vraie_moy == pytest.approx(moy, abs=1e-6), (
        "_serie a produit une moyenne de %+.6f au lieu de %+.6f" % (vraie_moy, moy))
    assert vraie_part == pytest.approx(part_pos, abs=2.0 / n), (
        "_serie a produit %.4f d'heures positives au lieu de %.4f -- ***elle mentait***"
        % (vraie_part, part_pos))
    return s


def test_l_AIDE_DE_TEST_ne_peut_plus_mentir() -> None:
    """🔒 **On teste l'AIDE elle-meme.** *Elle a deja rendu 3 tests aveugles ; plus jamais.*

    Les deux formes exactes qui produisaient 100 %% d'heures positives en silence.
    """
    for moy, part in ((0.30, 0.50), (0.50, 0.99), (0.10, 0.50), (-0.84, 0.83), (-0.99, 0.37)):
        s = _serie(moy, part)
        assert sum(1 for x in s if x > 0) / len(s) == pytest.approx(part, abs=1e-3), (
            "_serie(%s, %s) ment encore" % (moy, part))
        assert sum(s) / len(s) == pytest.approx(moy, abs=1e-6)

    # et si on FORCE un `pos` invalide, elle doit REFUSER -- pas produire une serie fausse.
    with pytest.raises(AssertionError):
        _serie(0.30, 0.50, pos=0.30)


# ════════════════════════════════════════════════════════════════════════════════════════════
# PORTE 1 — LE SPOT
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_un_coin_SANS_spot_est_refuse_meme_avec_un_funding_MAGNIFIQUE() -> None:
    """*Sans spot, on n'est pas delta-neutre : on est short le perp **A NU**.*

    NEAR avait **+0,133 bps/h** -- le 2e meilleur funding. **Il n'a pas de spot HL.**
    """
    p = scanner({"NEAR": _serie(0.50, 0.99)}, spot_carryables=SPOT)[0]
    assert not p.retenu and p.motif == MOTIF_PAS_DE_SPOT


# ════════════════════════════════════════════════════════════════════════════════════════════
# PORTE 2 — LE SIGNE
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_un_funding_NEGATIF_est_refuse_car_shorter_le_spot_est_IMPOSSIBLE() -> None:
    """STABLE : **-0,99 bps/h**. Spectaculaire... et **inaccessible**."""
    p = scanner({"STABLE": _serie(-0.99, 0.37)}, spot_carryables=SPOT)[0]
    assert not p.retenu and p.motif == MOTIF_FUNDING_NEGATIF


# ════════════════════════════════════════════════════════════════════════════════════════════
# 🔴🔴 PORTE 3 — LA STABILITE. **LE PIEGE QUE 365 JOURS A REVELE.**
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_AZTEC_le_piege_que_365_jours_a_revele() -> None:
    """🔴🔴 **J'AVAIS ANNONCE AZTEC A +5,7 % APR SUR 120 JOURS. IL PERD.**

    Sur son historique complet : **-0,84 bps/h de moyenne**... avec **83 % d'heures POSITIVES**.

    ***Des centaines de petites heures qui rapportent, et quelques-unes qui arrachent tout.***
    C'est exactement la queue qui tue un carry -- et la fenetre de 120 jours la CACHAIT.

    -> On exige **LES DEUX** : moyenne positive **ET** stabilite. *Un seul des deux ment.*
    """
    p = scanner({"AZTEC": _serie(-0.84, 0.83)}, spot_carryables=SPOT)[0]
    assert not p.retenu
    assert p.motif == MOTIF_FUNDING_NEGATIF, (
        "la moyenne NEGATIVE doit tomber AVANT le test de stabilite -- "
        "83 % d'heures positives ne sauvent pas une moyenne negative"
    )
    assert p.part_heures_positives > PART_HEURES_POSITIVES_MIN, (
        "🔴 et c'est BIEN la le piege : il est STABLE... et il PERD."
    )


def test_un_funding_positif_mais_INSTABLE_est_refuse() -> None:
    """Moyenne positive, mais seulement 50 % d'heures positives -> trop erratique.

    🔴 **CE TEST ETAIT AVEUGLE.** Il appelait `_serie(0.30, 0.50)` -- or moy == pos == 0,30
    faisait retomber la valeur « negative » sur **+0,30** : la serie etait **100 % positive**.
    Il croyait tester l'instabilite ; il testait un funding parfaitement stable.

    -> on demande une moyenne (**+0,10**) **distincte** de la valeur positive (+0,30), et
       l'aide `_serie` **VERIFIE** desormais qu'elle a bien produit 50 % d'heures positives.
    """
    serie = _serie(0.10, 0.50)
    assert sum(1 for x in serie if x > 0) / len(serie) == pytest.approx(0.50, abs=1e-3), (
        "prealable : la serie doit VRAIMENT avoir 50 % d'heures positives"
    )
    p = scanner({"HYPE": serie}, spot_carryables=SPOT)[0]
    assert not p.retenu and p.motif == MOTIF_INSTABLE


# ════════════════════════════════════════════════════════════════════════════════════════════
# PORTE 4 — L'ECONOMIE, et LES SURVIVANTS
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_PURR_le_meilleur_carry_mesure_du_projet_est_RETENU() -> None:
    """**+0,29 bps/h, positif 98 % du temps, sur 365 JOURS pleins.**
    Le chiffre le plus stable que ce projet ait produit."""
    p = scanner({"PURR": _serie(0.29, 0.98)}, spot_carryables=SPOT)[0]
    assert p.retenu and p.motif == MOTIF_RETENU
    assert p.apr_sur_capital > 0.10, "~12,7 % APR sur le capital des DEUX jambes"
    assert p.strategie == "CARRY"        # -> famille CARRY_STRUCTUREL -> franchit le noyau


def test_un_historique_TROP_COURT_ne_donne_AUCUN_verdict() -> None:
    """*Un carry se mesure sur des mois, pas sur une semaine.*"""
    p = scanner({"PURR": _serie(0.50, 0.99, n=100)}, spot_carryables=SPOT)[0]
    assert not p.retenu and p.motif == MOTIF_HISTORIQUE_COURT
    assert MIN_HEURES_HISTORIQUE == 720


def test_la_liste_du_spot_ABSENTE_ne_retient_RIEN() -> None:
    """🔴 DENY-BY-DEFAULT : sans la liste MESUREE, **on ne devine pas**."""
    props = scanner({"PURR": _serie(0.29, 0.98)}, spot_carryables=set())
    assert not any(p.retenu for p in props)


def test_le_rapport_dit_que_le_NOYAU_rejuge_TOUT() -> None:
    """***Le scanner PROPOSE. Le noyau DISPOSE.*** Aucune porte n'est sautee."""
    r = rapport(scanner({"PURR": _serie(0.29, 0.98), "BERA": _serie(-0.83, 0.40)},
                        spot_carryables=SPOT))
    assert r["n_retenus"] == 1
    assert "Le noyau DISPOSE" in r["note"]
    assert "carnet de 3 $" in r["avertissement"]
    assert r["real_execution"] is False


def test_le_classement_range_la_shortlist_par_carry_net() -> None:
    """CABLAGE (16/07) : classement_shortlist compose scanner + carry_ranking -> les retenus,
    ranges par carry NET predit. Rien n'est ouvert ici -- le noyau garde l'autorite."""
    from hl_observer.strategies.carry_scanner import classement_shortlist
    fundings = {"HYPE": [3.0] * 8760, "PURR": [1.5] * 8760, "STABLE": [-0.99] * 8760}
    cl = classement_shortlist(fundings, spot_carryables=SPOT, cout_amorti_bps_h=0.5)
    coins = [c.coin for c in cl]
    assert "STABLE" not in coins            # funding negatif -> refuse par le scanner
    assert coins == ["HYPE", "PURR"]         # HYPE (3.0) devant PURR (1.5)
    assert cl[0].net_bps_h > cl[1].net_bps_h
