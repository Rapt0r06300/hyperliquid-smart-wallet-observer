"""#595 — le regime est ENFIN branche dans la recherche. Sans lire le futur.

Le gate `regime_robustness` reclamait un champ `regime` que personne n'ecrivait (#127). Depuis
#127 il le DECLARE (`mode: tranches_temporelles_FAUTE_DE_LABEL`) -- mais un aveu n'est pas une
solution. Ici on lui donne ce qu'il demande.

Les trois tests qui comptent :
  1. le label est **CAUSAL** (test differentiel : changer le futur ne change AUCUN label passe) ;
  2. le seuil vient du **TRAIN SEUL** (le calculer sur tout l'echantillon serait un lookahead) ;
  3. le gate bascule vraiment en `mode: regime` -- et le pass/fail des AUTRES gates ne bouge pas.
"""

from __future__ import annotations

from hl_observer.backtesting.regime_label import BASSE_VOL, HAUTE_VOL, INCONNU
from hl_observer.backtesting.regime_wiring import (
    etiqueter_triplets,
    preparer,
    regime_du_trade,
    repartition,
    serie_causale,
)
from hl_observer.backtesting.validation_gates import run_validation_gates

# Un marche CALME (pas de 0,1 %) puis AGITE (pas de 5 %). Deterministe, aucun seed a trahir.
CALME = [(float(i), 100.0 * (1.0 + 0.001 * (i % 2))) for i in range(60)]
AGITE = [(float(60 + i), 100.0 * (1.0 + 0.05 * (i % 2))) for i in range(60)]
CHEMIN = CALME + AGITE
MARKS = {"BTC": CHEMIN}
FIN_TRAIN = 59.0


def test_la_serie_est_CAUSALE_le_futur_ne_change_pas_le_passe():
    """🔴 LE TEST QUI NE PEUT PAS ETRE TROMPE (methode H-157).

    On ne lit pas le code : on change le FUTUR et on verifie que le PASSE ne bouge pas.
    C'est ce test qui a demasque `garch11_variance` (#127) -- elle ECHOUE, elle.
    """
    a = serie_causale(CHEMIN)
    b = serie_causale(CHEMIN[:-20] + [(float(100 + i), 500.0) for i in range(20)])

    n = min(len(a.ts), len(b.ts))
    passe_a = [(t, v) for t, v in zip(a.ts[:n], a.var[:n]) if t <= 80.0]
    passe_b = [(t, v) for t, v in zip(b.ts[:n], b.var[:n]) if t <= 80.0]
    assert passe_a == passe_b, (
        "une variance PASSEE a change alors que seul le FUTUR a ete modifie : "
        "l'etiquetage lit devant lui."
    )


def test_la_variance_connue_a_un_instant_n_utilise_QUE_le_passe():
    """`variance_connue_a(t)` doit rendre le dernier point <= t. Jamais le suivant.

    C'est LA ligne ou un lookahead se glisse par distraction (`bisect_left` au lieu de
    `bisect_right`). On la teste explicitement.
    """
    s = serie_causale(CHEMIN)
    t0 = s.ts[5]
    assert s.variance_connue_a(t0) == s.var[5]
    assert s.variance_connue_a(t0 - 0.5) == s.var[4]
    assert s.variance_connue_a(s.ts[0] - 1.0) is None, "avant le 1er point, on ne SAIT pas"


def test_le_seuil_vient_du_TRAIN_SEUL():
    """Un seuil calcule sur train+test connaitrait le futur. Lookahead discret, mais reel."""
    prep_train = preparer(MARKS, FIN_TRAIN)
    prep_tout = preparer(MARKS, 200.0)          # seuil calcule sur TOUT (ce qu'il ne faut PAS faire)

    s1 = prep_train.seuils["BTC"].seuil
    s2 = prep_tout.seuils["BTC"].seuil
    assert s1 != s2, (
        "le seuil est identique qu'on l'estime sur le train ou sur tout l'echantillon : "
        "soit les donnees de test sont dans le train, soit le seuil ne sert a rien."
    )
    assert s1 < s2, "le train est CALME : son seuil doit etre plus BAS que celui de tout l'echantillon"


def test_le_regime_separe_vraiment_le_CALME_de_l_AGITE():
    """Le module doit MESURER quelque chose de reel -- pas seulement etre causal et vide.

    🚩 MON PREMIER TEST ETAIT FAUX, PAS LE CODE.
    J'attendais que TOUT le calme soit BASSE_VOL. Mais le seuil est la **mediane du train** :
    par construction, elle coupe le train **en deux**. Un instant de la phase calme a donc une
    chance sur deux de tomber au-dessus. Ce n'est pas un defaut -- c'est la definition meme
    d'une mediane.

    Ce qu'il faut verifier, c'est ce qui est VRAI :
      * la phase AGITEE (hors du train) est **entierement** au-dessus du seuil du train ;
      * la phase CALME (le train) est **partagee** de part et d'autre.
    """
    prep = preparer(MARKS, FIN_TRAIN)

    assert regime_du_trade(prep, "BTC", 5.0) == INCONNU, "avant la fin du warmup, on ne SAIT pas"

    # AGITE : tout doit basculer HAUTE_VOL. C'est LA propriete qui rend le label utile.
    agite = [regime_du_trade(prep, "BTC", float(t)) for t in range(95, 119)]
    assert set(agite) == {HAUTE_VOL}, (
        "la phase agitee n'est pas vue comme HAUTE_VOL : le label ne mesure rien. Vu : %s"
        % sorted(set(agite))
    )

    # CALME (= le train) : la mediane le coupe en deux. Les DEUX etiquettes doivent apparaitre.
    calme = [regime_du_trade(prep, "BTC", float(t)) for t in range(25, 60)]
    assert set(calme) == {BASSE_VOL, HAUTE_VOL}, (
        "la mediane du train ne partage pas le train en deux : ce n'est donc pas une mediane. "
        "Vu : %s" % sorted(set(calme))
    )


def test_un_coin_SANS_SEUIL_credible_reste_INCONNU():
    """Deny-by-default : pas d'historique => pas de label. On ne devine pas un regime."""
    prep = preparer({"NOUVEAU": [(0.0, 100.0), (1.0, 101.0), (2.0, 99.0)]}, 2.0)
    assert regime_du_trade(prep, "NOUVEAU", 2.0) == INCONNU
    assert regime_du_trade(prep, "JAMAIS_VU", 2.0) == INCONNU


def test_le_GATE_bascule_en_mode_REGIME_et_les_AUTRES_gates_ne_bougent_pas():
    """🔴 LE CŒUR DE #595.

    Avant : `eval_trades` rendait des floats -> la branche « regime » du gate etait
    STRUCTURELLEMENT INATTEIGNABLE. Maintenant elle est atteinte.

    Et surtout : les AUTRES gates (profit factor, OOS, Monte-Carlo) lisent `net_pnl_usdc` via
    `_pnls` -- donc leur verdict est IDENTIQUE. On n'a rien casse en chemin, et on n'a pas profite
    de la correction pour bouger un seuil.
    """
    prep = preparer(MARKS, FIN_TRAIN)
    triplets = [("BTC", 55.0, 3.0), ("BTC", 57.0, -1.0), ("BTC", 110.0, 4.0), ("BTC", 112.0, -2.0)]
    labellises = etiqueter_triplets(prep, triplets)
    bruts = [p for _c, _t, p in triplets]

    avec = run_validation_gates(labellises)
    sans = run_validation_gates(bruts)

    g_avec = next(g for g in avec["gates"] if g["gate"] == "regime_robustness")
    g_sans = next(g for g in sans["gates"] if g["gate"] == "regime_robustness")

    assert g_sans["mode"] == "tranches_temporelles_FAUTE_DE_LABEL"
    assert g_avec["mode"] == "regime", "le gate n'a PAS bascule : le label n'arrive pas jusqu'a lui"
    assert g_avec["regime_labels_presents"] is True

    # Les autres gates : verdict INCHANGE. La correction n'a rien deplace en douce.
    for nom in ("sample_size", "profit_factor", "out_of_sample", "monte_carlo_dd"):
        a = next(g for g in avec["gates"] if g["gate"] == nom)
        s = next(g for g in sans["gates"] if g["gate"] == nom)
        assert a["passed"] == s["passed"], "le gate %s a change de verdict : ce n'etait PAS demande" % nom


def test_la_repartition_AVOUE_les_INCONNU():
    """Un `INCONNU` massif est un AVEU (pas assez d'historique), pas un detail cosmetique."""
    prep = preparer(MARKS, FIN_TRAIN)
    trades = etiqueter_triplets(prep, [("BTC", 5.0, 1.0), ("BTC", 110.0, 1.0), ("BTC", 112.0, 1.0)])
    rep = repartition(trades)

    assert rep[INCONNU] == 1, "le trade d'avant le warmup DOIT etre avoue comme INCONNU"
    assert rep[HAUTE_VOL] == 2
    assert sum(rep.values()) == 3, "aucun trade ne doit disparaitre de la repartition"
