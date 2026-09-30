"""H-181 -- LA MALEDICTION DU VAINQUEUR, DEMONTREE SUR DU BRUIT PUR.

Le code selectionne les 40 finalistes par le MAXIMUM du PnL de train. Ces tests montrent, sur
du bruit FABRIQUE (donc sans le moindre edge, par construction), que :

  1. le maximum d'un bruit est TOUJOURS positif, et il MONTE avec le nombre de configs testees ;
  2. la selection par MAXIMUM ramasse donc systematiquement des pics de chance ;
  3. la selection par PLATEAU ne se laisse pas prendre : un pic isole a des voisins mediocres.

Si ces trois choses sont vraies sur du bruit pur, elles le sont a fortiori sur nos donnees.

Aucun ordre reel.
"""
from __future__ import annotations

import random

from hl_observer.backtesting.overfit_selection import (
    VERDICT_AUCUN_GAGNANT,
    VERDICT_BRUIT,
    VERDICT_SIGNAL,
    borne_du_hasard,
    permuter_les_sens,
    selection_par_maximum,
    selection_par_plateau,
)


# ====================================================== 1. LE MAXIMUM D'UN BRUIT


def test_le_maximum_d_un_BRUIT_est_toujours_positif_et_MONTE_avec_le_nombre_d_essais():
    """LA mecanique de la malediction du vainqueur, en une ligne de code.

    Aucune de ces « configs » n'a d'edge : leur score est un tirage centre sur ZERO. Et pourtant
    le meilleur est toujours nettement positif -- et il monte quand on en teste plus.

    C'est exactement ce que fait la recherche : elle prend le MAXIMUM sur 150 000 000 de tirages.
    """
    rng = random.Random(20260713)
    maxima = {}
    for n in (100, 1_000, 10_000, 100_000):
        scores = [(i, rng.gauss(0.0, 1.0)) for i in range(n)]
        maxima[n] = max(s for _i, s in scores)

    for n, m in maxima.items():
        assert m > 0.0, f"le max de {n} tirages centres sur zero devrait etre positif"

    # Et il MONTE. C'est ca qui est vicieux : plus on cherche, plus on « trouve ».
    assert maxima[100_000] > maxima[10_000] > maxima[1_000] > maxima[100], (
        "le maximum devrait croitre avec le nombre d'essais -- sinon la demonstration tombe"
    )


def test_la_borne_du_hasard_DENONCE_un_max_qui_ressemble_au_bruit():
    """Si le max reel est du meme ordre que les max permutes, c'est du bruit. On le DIT."""
    b = borne_du_hasard(max_reel=42.0, maxima_permutes=[38.0, 41.0, 45.0, 40.0, 44.0],
                        n_scenarios=100_000)
    assert b.verdict == VERDICT_BRUIT
    assert b.max_hasard_p95 > 0


def test_la_borne_du_hasard_RECONNAIT_un_vrai_signal():
    """Et elle ne crie pas au loup quand le reel ecrase le hasard."""
    b = borne_du_hasard(max_reel=500.0, maxima_permutes=[38.0, 41.0, 45.0, 40.0, 44.0],
                        n_scenarios=100_000)
    assert b.verdict == VERDICT_SIGNAL
    assert b.ratio > 5.0


def test_sans_permutation_on_ne_conclut_PAS():
    b = borne_du_hasard(max_reel=100.0, maxima_permutes=[], n_scenarios=10)
    assert b.verdict == "INSUFFICIENT_DATA", "conclure sans controle serait pire que ne rien dire"


# ============================================ 1bis. LE BUG QUI A FAIT MENTIR MON PROPRE OUTIL
#
# 2026-07-13, sur les VRAIES donnees, l'outil a imprime « INDISCERNABLE DU HASARD » alors que
#     max_reel = -106,46 $   et   p95 du hasard = -224,94 $
# soit un reel **118 $ AU-DESSUS** du hasard. La cause etait dans la comparaison :
#
#     seuil = p95 * marge if p95 > 0 else 0.0     # <-- s'effondre a 0 quand p95 <= 0
#     verdict = SIGNAL if max_reel > seuil ...    #     -> exige max_reel > 0
#
# Sur un marche perdant (PnL moyen par trade NEGATIF), le p95 du null est negatif : le verdict
# devenait donc MECANIQUEMENT « BRUIT ». Un outil de mesure qui se trompe est PIRE qu'une
# absence de mesure : on lui fait confiance.


def test_le_signe_NEGATIF_ne_doit_PAS_ecraser_le_seuil_a_zero():
    """🔴 LE TEST QUI AURAIT ATTRAPE LE BUG. Reel au-dessus du hasard, mais tout est negatif."""
    b = borne_du_hasard(
        max_reel=-106.46,
        maxima_permutes=[-300.0, -280.0, -260.0, -240.0, -224.94],
        n_scenarios=400,
    )
    assert b.max_hasard_p95 < 0, "le p95 du null EST negatif ici : c'est tout le probleme"
    assert b.ecart > 0, "le reel est AU-DESSUS du hasard : l'ecart doit etre positif"
    assert round(b.ecart, 2) == 118.48, "ecart = -106.46 - (-224.94) = +118.48 $"
    # Et le verdict n'est PAS « bruit » : il est « aucun gagnant », ce qui est la verite.
    assert b.verdict == VERDICT_AUCUN_GAGNANT


def test_AUCUN_GAGNANT_quand_meme_le_meilleur_PERD_en_train():
    """🔴 LE VERDICT QUI COMPTE : s'il n'y a pas de vainqueur, il n'y a pas de malediction.

    C'est le cas MESURE le 2026-07-13 : le meilleur des 400 scenarios fait -106 $ **en train**,
    la ou il a pourtant tous les droits de sur-ajuster. Discuter de la procedure de selection
    n'a alors plus aucun sens -- il n'y a rien a selectionner.
    """
    b = borne_du_hasard(max_reel=-0.01, maxima_permutes=[-50.0, -40.0, -30.0], n_scenarios=100)
    assert b.verdict == VERDICT_AUCUN_GAGNANT
    b2 = borne_du_hasard(max_reel=0.0, maxima_permutes=[-50.0], n_scenarios=100)
    assert b2.verdict == VERDICT_AUCUN_GAGNANT, "zero non plus n'est pas un gain"


def test_le_ratio_ne_MENT_plus_quand_les_valeurs_sont_negatives():
    """Un ratio de negatifs n'a aucun sens. On rend 0.0 et on publie l'ECART, qui en a un."""
    b = borne_du_hasard(max_reel=-106.46, maxima_permutes=[-224.94], n_scenarios=10)
    assert b.ratio == 0.0, "on ne publie PAS un ratio trompeur ; on publie l'ecart"
    assert b.as_dict()["ecart_vs_p95"] > 0


def test_la_marge_est_ADDITIVE_donc_valable_sur_des_negatifs():
    """Une marge MULTIPLICATIVE ferait DESCENDRE un seuil negatif. Absurde. Elle est additive."""
    # Sans marge : le reel (+10) depasse le p95 (+5) -> signal.
    assert borne_du_hasard(max_reel=10.0, maxima_permutes=[5.0],
                           n_scenarios=10).verdict == VERDICT_SIGNAL
    # Avec 20 $ de marge exigee : 10 > 5 + 20 est FAUX -> bruit. La marge DURCIT, jamais l'inverse.
    assert borne_du_hasard(max_reel=10.0, maxima_permutes=[5.0], n_scenarios=10,
                           marge_usd=20.0).verdict == VERDICT_BRUIT


# ====================================================== 2. LES DEUX SELECTIONS


def _vecteur(sc):
    """sc = (x, y) : deux coordonnees normalisees."""
    return (float(sc[0]), float(sc[1]))


def test_le_PLATEAU_ne_se_laisse_PAS_prendre_par_un_pic_de_chance():
    """LE test qui justifie le correctif.

    On fabrique un paysage : du bruit partout, SAUF une vraie zone d'edge (un plateau) et UN
    pic de chance isole, plus haut que tout le reste.

      * La selection par MAXIMUM ramasse le pic. Elle se fait avoir.
      * La selection par PLATEAU l'ignore : ses voisins sont mediocres.
    """
    rng = random.Random(7)
    scores: list[tuple[tuple[float, float], float]] = []

    # bruit de fond (centre sur zero)
    for i in range(30):
        for j in range(30):
            scores.append(((i / 30.0, j / 30.0), rng.gauss(0.0, 1.0)))

    # une VRAIE zone d'edge : un plateau autour de (0.5, 0.5) -- tout le voisinage est bon
    for i in range(13, 18):
        for j in range(13, 18):
            scores.append(((i / 30.0, j / 30.0), 5.0 + rng.gauss(0.0, 0.3)))

    # UN pic de chance, isole, PLUS HAUT que le plateau
    scores.append(((0.95, 0.05), 12.0))

    top_max = selection_par_maximum(scores, 1)
    top_plateau = selection_par_plateau(scores, 1, vecteur=_vecteur, voisins=8)

    assert top_max[0] == (0.95, 0.05), "le maximum DOIT ramasser le pic : c'est le probleme"
    x, y = top_plateau[0]
    assert 0.40 <= x <= 0.60 and 0.40 <= y <= 0.60, (
        f"le plateau a ramasse {top_plateau[0]} au lieu de la vraie zone d'edge : "
        "le correctif ne corrige rien"
    )


def test_le_plateau_ne_rend_PAS_le_pic_isole_meme_dans_le_top_10():
    """Un pic entoure de bruit ne doit pas remonter, meme en elargissant."""
    rng = random.Random(11)
    scores = [((i / 20.0, j / 20.0), rng.gauss(0.0, 1.0))
              for i in range(20) for j in range(20)]
    scores.append(((0.975, 0.025), 50.0))          # pic ENORME, mais seul au monde

    top = selection_par_plateau(scores, 10, vecteur=_vecteur, voisins=8)
    assert (0.975, 0.025) not in top, (
        "un pic isole a 50 (contre un bruit a ~1) a quand meme ete retenu : le plateau est casse"
    )


# ====================================================== 3. LA PERMUTATION


def test_permuter_les_sens_DETRUIT_l_edge_et_RIEN_d_autre():
    """Si la permutation cassait autre chose (le coin, le prix, l'horodatage), le controle ne
    serait pas comparable -- et sa conclusion serait sans valeur."""
    cands = [
        {"coin": "BTC", "direction": "LONG", "recorded_at": 1.0, "current_mid": 100.0,
         "signal_age_ms": 500, "leader_score": 70, "liquidity_score": 0.8},
        {"coin": "ETH", "direction": "SHORT", "recorded_at": 2.0, "current_mid": 50.0,
         "signal_age_ms": 900, "leader_score": 60, "liquidity_score": 0.5},
    ]
    faux = permuter_les_sens(cands, seed=1)

    assert len(faux) == len(cands)
    for a, b in zip(cands, faux):
        for cle in ("coin", "recorded_at", "current_mid", "signal_age_ms",
                    "leader_score", "liquidity_score"):
            assert a[cle] == b[cle], f"la permutation a abime `{cle}` : le controle est invalide"
        assert b["direction"] in ("LONG", "SHORT")


def test_permuter_les_sens_est_DETERMINISTE_a_seed_egale():
    """Un controle qu'on ne peut pas reproduire n'est pas un controle."""
    cands = [{"coin": "BTC", "direction": "LONG", "recorded_at": float(i), "current_mid": 100.0}
             for i in range(50)]
    a = permuter_les_sens(cands, seed=42)
    b = permuter_les_sens(cands, seed=42)
    c = permuter_les_sens(cands, seed=43)
    assert [x["direction"] for x in a] == [x["direction"] for x in b]
    assert [x["direction"] for x in a] != [x["direction"] for x in c]


def test_la_permutation_change_VRAIMENT_les_sens():
    """Une permutation qui ne permute rien passerait tous les controles -- et ne prouverait rien."""
    cands = [{"coin": "BTC", "direction": "LONG", "recorded_at": float(i), "current_mid": 100.0}
             for i in range(200)]
    faux = permuter_les_sens(cands, seed=3)
    shorts = sum(1 for c in faux if c["direction"] == "SHORT")
    assert 60 < shorts < 140, f"repartition suspecte ({shorts}/200) : la permutation ne melange pas"
