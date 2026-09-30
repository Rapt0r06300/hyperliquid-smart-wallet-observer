"""🔴 LES QUATRE TROUS QUE LE MUTATION TESTING A TROUVES (2026-07-13, IDEA-93).

Le mutation testing a casse le code expres et a trouve **quatre bugs plausibles que la suite
laissait passer EN SILENCE**. Aucun n'aurait ete trouve par la couverture de lignes : ces lignes
etaient toutes EXECUTEES -- elles n'etaient simplement pas **VERIFIEES**.

    « ce code a ete EXECUTE »  n'est PAS  « ce code a ete VERIFIE ».

Les quatre, et ce que chacun aurait coute :

  1. `edge_calculator.py:50`  `+` -> `-`  entre deux couts.
     C'est LA formule qui autorise ou refuse **chaque entree du bot**. Un signe inverse entre
     `taker_fee` et `spread_cost` rendrait les couts plus PETITS -> le bot accepterait des trades
     perdants. Les tests ne l'attrapaient pas : ils ne mettaient **jamais deux couts differents
     non nuls en meme temps**.

  2. `dead_zones.py:159`  `<` -> `<=`  sur `echantillon < MIN_ECHANTILLON`.
     La BORNE. Une zone morte avec EXACTEMENT 30 observations etait-elle acceptee ou refusee ?
     Personne ne l'avait fige. **C'est la meme famille que le bug de #588**, ou `>` au lieu de
     `>=` declarait liquidee une marge qui survivait EXACTEMENT.

  3. `funding_carry_economics.py:127`  `>` -> `>=`  sur `if bruit > 0`.
     Le garde contre la **division par zero**. Aucun test ne passait `bruit = 0` : le garde
     existait, personne ne verifiait qu'il gardait.

  4. `carry_liquidation_risk.py:78`  `SEUIL_BACKSTOP = 2.0 / 3.0` -> `2.0 * 3.0`.
     🚩 **LE PIRE** : la constante est definie, EXPORTEE dans `__all__`... et **utilisee NULLE
     PART**. Je l'ai ecrite HIER (#588) en documentant la regle Hyperliquid (« the maintenance
     margin is not returned to the user ») et je ne l'ai **jamais branchee dans le calcul**.
     *Le mutation testing a trouve un trou dans mon propre travail de la veille.*
     -> traite dans `test_carry_liquidation_risk.py` (le backstop est desormais CALCULE).

Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.agent.dead_zones import MIN_ECHANTILLON, PreuveInsuffisante, creer_zone_morte
from hl_observer.edge.edge_calculator import EdgeNetInputs, compute_net_edge
from hl_observer.funding.carry_liquidation_risk import (
    SEUIL_BACKSTOP,
    backstop_declenche,
    perte_seche_si_backstop,
)
from hl_observer.funding.funding_carry_economics import evaluer_carry


# =============================================================================================
# 1. LA SOMME DES COUTS -- la formule qui decide de TOUTES les entrees
# =============================================================================================


def test_les_couts_S_ADDITIONNENT_ils_ne_se_SOUSTRAIENT_pas():
    """🔴 MUTANT `Add->Sub` SURVIVANT (edge_calculator.py:50).

    Chaque cout doit AUGMENTER le cout total. Si un `+` devenait un `-`, le bot verrait des couts
    plus petits qu'ils ne sont -- et accepterait des trades perdants **en croyant les refuser**.

    Le test manquant etait simple : mettre **plusieurs couts DIFFERENTS et non nuls en meme
    temps**. Tant qu'un seul cout est non nul, `a + b` et `a - b` donnent le meme resultat.
    C'est exactement pourquoi la suite etait verte.

    🚩 ET MA 1re VERSION DE CE TEST A ECHOUE -- POUR LA RAISON QUE JE VENAIS D'ECRIRE.
    J'avais mis CINQ couts non nuls... et laisse `funding_cost_bps = 0.0`. Or il y en a **SIX**
    (je n'avais jamais lu la ligne 55). Muter le `+` devant un **zero** ne change rien : le
    mutant a survecu une 2e fois, et le score est reste bloque a 97,5 %.
    *J'ai commis EXACTEMENT la faute que je decrivais deux lignes plus haut, dans mon propre
    docstring.* C'est le mutation testing qui me l'a dit. **Rien d'autre ne l'aurait fait.**
    """
    r = compute_net_edge(EdgeNetInputs(
        gross_edge_bps=100.0,
        taker_fee_bps=3.0,
        spread_cost_bps=5.0,
        slippage_bps=7.0,
        latency_decay_bps=11.0,
        copy_degradation_bps=13.0,
        funding_cost_bps=17.0,            # <-- LE 6e COUT. Il DOIT etre non nul, sinon le test ment.
    ))
    assert r.total_cost_bps == pytest.approx(3 + 5 + 7 + 11 + 13 + 17), (
        "les couts ne s'additionnent pas : total=%.2f au lieu de 56. Un signe est inverse."
        % r.total_cost_bps
    )
    assert r.net_edge_bps == pytest.approx(100.0 - 56.0)


@pytest.mark.parametrize("champ", [
    "taker_fee_bps", "spread_cost_bps", "slippage_bps",
    "latency_decay_bps", "copy_degradation_bps",
    "funding_cost_bps",                   # <-- OUBLIE dans ma 1re version. Le mutant l'a vu.
])
def test_CHAQUE_cout_pris_isolement_AUGMENTE_le_cout_total(champ: str):
    """Aucun cout ne peut, seul, faire BAISSER le cout total. Un seul signe inverse suffirait a
    fabriquer un edge -- et ce projet a deja produit trois edges fabriques."""
    base = compute_net_edge(EdgeNetInputs(gross_edge_bps=100.0)).total_cost_bps
    avec = compute_net_edge(EdgeNetInputs(**{"gross_edge_bps": 100.0, champ: 10.0})).total_cost_bps
    assert avec > base, "%s ne fait pas monter le cout total : son signe est inverse" % champ


def test_le_REBATE_maker_lui_FAIT_BAISSER_le_cout_c_est_le_seul():
    """La seule exception, et elle est VOULUE : un rebate maker se SOUSTRAIT.

    Il faut la figer explicitement -- sinon, le jour ou quelqu'un « corrige » ce `-` en `+`
    (parce que « tous les autres sont des `+` »), le bot paierait un rebate au lieu de
    l'encaisser, et personne ne le verrait.

    ⚠️ Chez Hyperliquid, le maker **PAIE** 1,5 bps : ce champ vaut 0 en pratique. Raison de plus
    pour le tester -- *un champ toujours nul est un champ que personne ne regarde.*
    """
    sans = compute_net_edge(EdgeNetInputs(gross_edge_bps=100.0, taker_fee_bps=10.0))
    avec = compute_net_edge(EdgeNetInputs(gross_edge_bps=100.0, taker_fee_bps=10.0,
                                          maker_rebate_bps=4.0))
    assert avec.total_cost_bps == pytest.approx(sans.total_cost_bps - 4.0)
    assert avec.net_edge_bps > sans.net_edge_bps


# =============================================================================================
# 2. LA BORNE DE L'ECHANTILLON -- la meme famille que le bug de #588
# =============================================================================================


def test_un_echantillon_EXACTEMENT_egal_au_minimum_est_ACCEPTE():
    """🔴 MUTANT `Lt->LtE` SURVIVANT (dead_zones.py:159).

    `if echantillon < MIN_ECHANTILLON: refuser`. Donc a EXACTEMENT MIN_ECHANTILLON, on ACCEPTE.
    Personne ne l'avait fige. C'est la borne, et **les bornes sont ou vivent nos bugs** :
    #588 declarait liquidee une marge qui survivait EXACTEMENT au pire mouvement.
    """
    z = creer_zone_morte(
        id="PILE_AU_MINIMUM", hypothese="h", verdict="v", mesure="m", valeur=-1.0, unite="bps",
        echantillon=MIN_ECHANTILLON,                # <-- PILE la borne
        lecon="une regle generale", condition_de_reouverture="des donnees neuves",
        entree_mesuree="une_entree",
    )
    assert z.echantillon == MIN_ECHANTILLON


def test_un_echantillon_d_UNE_UNITE_sous_le_minimum_est_REFUSE():
    """L'autre cote de la borne. Les deux tests ensemble la CLOUENT."""
    with pytest.raises(PreuveInsuffisante):
        creer_zone_morte(
            id="UN_DE_TROP_PEU", hypothese="h", verdict="v", mesure="m", valeur=-1.0, unite="bps",
            echantillon=MIN_ECHANTILLON - 1,
            lecon="une regle generale", condition_de_reouverture="des donnees neuves",
            entree_mesuree="une_entree",
        )


# =============================================================================================
# 3. LE GARDE CONTRE LA DIVISION PAR ZERO -- il existait, personne ne verifiait qu'il gardait
# =============================================================================================


def test_un_bruit_de_prix_NUL_ne_fait_pas_planter_le_carry():
    """🔴 MUTANT `Gt->GtE` SURVIVANT (funding_carry_economics.py:127).

    `ratio = f / bruit if bruit > 0 else inf`. Avec `>=`, un bruit nul divise par zero -> crash.
    Le mutant a SURVECU : **aucun test ne passait `bruit = 0`.**

    Un marche a bruit nul n'existe pas en pratique -- mais un capteur casse, oui. Et un bot qui
    plante sur une donnee degeneree est un bot qui s'arrete la nuit (on l'a deja vecu : le run de
    48 h a gele deux fois).
    """
    # jambe NUE : refusee de toute facon -- mais elle ne doit pas PLANTER.
    nue = evaluer_carry(
        funding_bps_h=2.0, bruit_prix_bps_h=0.0, cout_aller_retour_bps=12.0, couvert=False,
    )
    assert nue is not None
    assert nue.couvert is False

    # jambe COUVERTE : le chemin qui calcule REELLEMENT le ratio f/bruit. C'est celui-la qui
    # diviserait par zero si le garde tombait.
    couverte = evaluer_carry(
        funding_bps_h=2.0, bruit_prix_bps_h=0.0, cout_aller_retour_bps=12.0, couvert=True,
    )
    assert couverte is not None


# =============================================================================================
# 4. 🚩 LE PIRE : UNE CONSTANTE ECRITE HIER, EXPORTEE... ET UTILISEE NULLE PART
# =============================================================================================


def test_le_SEUIL_BACKSTOP_vaut_bien_deux_tiers_et_pas_six():
    """🔴 MUTANT `Div->Mult` SURVIVANT (carry_liquidation_risk.py:78).

    `SEUIL_BACKSTOP = 2.0 / 3.0`. Mute en `2.0 * 3.0` (= 6.0), **aucun test ne bronchait** :
    la constante etait definie, EXPORTEE dans `__all__`... et **utilisee NULLE PART**.

    Je l'ai ecrite le 2026-07-12 (#588) en citant la doc Hyperliquid, et je ne l'ai jamais
    branchee. *Le mutation testing a trouve un trou dans mon propre travail de la veille* --
    et la couverture de lignes, elle, etait a 99,4 %.
    """
    assert SEUIL_BACKSTOP == pytest.approx(2.0 / 3.0)
    assert 0.0 < SEUIL_BACKSTOP < 1.0, (
        "un seuil de backstop >= 1 n'a aucun sens : il se declencherait AVANT la maintenance"
    )


def test_notre_hypothese_backstop_est_bien_la_borne_PESSIMISTE():
    """⚖️ L'HYPOTHESE, DESORMAIS DECLAREE ET VERROUILLEE.

    La doc dit : le backstop (et la confiscation de la marge) ne frappe que **sous 2/3 de la
    marge de maintenance**. Entre `mm` et `2/3*mm`, on est liquide SANS confiscation.

    `evaluer_risque_liquidation` suppose pourtant que le backstop se declenche **TOUJOURS**.
    C'est VOLONTAIRE : c'est la borne pessimiste. Ce test verrouille le SENS de l'hypothese --
    on ne pourra pas « optimiser » ce modele en douce pour se donner un meilleur chiffre.
    """
    mm = 0.1667                                   # levier 3x -> mm = 1/(2*3)
    # au-dessus du seuil : la doc dit PAS de confiscation...
    assert backstop_declenche(0.9 * mm, mm) is False
    # ... en dessous : confiscation.
    assert backstop_declenche(0.5 * mm, mm) is True

    # ... et NOTRE modele facture la confiscation dans les DEUX cas. C'est plus severe que la
    # doc : on prefere se tromper dans le sens qui nous COUTE.
    facture = perte_seche_si_backstop(mm, notionnel_usd=500.0)
    assert facture > 0, (
        "notre modele ne facture plus la confiscation : il vient de devenir OPTIMISTE sans "
        "qu'aucune mesure ne le justifie"
    )


# =============================================================================================
# 5. LA 2e PASSE DU MUTEUR (une fois les mutants EQUIVALENTS exclus) — 4 survivants de plus
# =============================================================================================


def test_un_edge_EXACTEMENT_egal_au_seuil_est_ACCEPTE():
    """🔴 MUTANT `Lt->LtE` SURVIVANT (edge_calculator.py:64) — **LA PORTE D'ENTREE DU BOT**.

    `elif net < min_edge_bps: REJETER`. Donc a `net == min_edge_bps` **EXACTEMENT**, on ACCEPTE.
    Personne ne l'avait fige. Muter `<` en `<=` **inverse la decision** sur cette valeur : le bot
    refuserait un trade qu'il acceptait, ou l'inverse -- **et la suite restait verte**.

    C'est la TROISIEME fois aujourd'hui que la meme famille de bug apparait (#588, dead_zones:159,
    et ici). *Les bornes sont ou vivent nos bugs.*
    """
    r = compute_net_edge(EdgeNetInputs(gross_edge_bps=40.0, taker_fee_bps=10.0),
                         min_edge_bps=30.0)             # net = 30.0 PILE
    assert r.net_edge_bps == pytest.approx(30.0)
    assert r.decision == "ACCEPT", (
        "un edge net EXACTEMENT egal au seuil doit etre ACCEPTE (`net < min` rejette). "
        "decision=%s" % r.decision
    )


def test_un_edge_d_un_cheveu_SOUS_le_seuil_est_REFUSE():
    """L'autre cote de la borne. Les deux ensemble la CLOUENT."""
    r = compute_net_edge(EdgeNetInputs(gross_edge_bps=40.0, taker_fee_bps=10.01),
                         min_edge_bps=30.0)             # net = 29.99
    assert r.decision == "REJECT_EDGE_TOO_SMALL"


def test_un_edge_net_EXACTEMENT_NUL_est_REJETE_comme_NEGATIF():
    """🔴 MUTANT `LtE->Lt` SURVIVANT (edge_calculator.py:61).

    `if net <= 0: REJECT_EDGE_NEGATIVE`. A net == 0 pile, le motif doit etre NEGATIF (pas
    « trop petit »). Un motif faux, c'est un diagnostic faux -- et on passe des heures a chercher
    au mauvais endroit. On l'a deja fait.
    """
    r = compute_net_edge(EdgeNetInputs(gross_edge_bps=10.0, taker_fee_bps=10.0), min_edge_bps=30.0)
    assert r.net_edge_bps == pytest.approx(0.0)
    assert r.decision == "REJECT_EDGE_NEGATIVE"


def test_une_SEULE_zone_rouverte_ne_leve_PAS_le_refus_des_AUTRES():
    """🔴 MUTANT `And->Or` SURVIVANT (dead_zones.py:292) — **ET C'EST LE PLUS GRAVE DES QUATRE.**

    Cette ligne EST le correctif du 2026-07-12 : *« le registre s'auto-desarmait »*. Il exige que
    **TOUTES** les zones touchees soient rouvertes pour lever le refus :

        if rouvertes AND len(rouvertes) == len(touchees):  -> pas de refus

    Mute en `OR`, **une seule** zone rouverte suffirait a blanchir une proposition qui en touche
    trois. C'est exactement le bug qu'on avait corrige... **et aucun test ne le tenait.** Il
    aurait pu revenir demain, en silence.
    """
    from hl_observer.agent.dead_zones_hypersmart import registre_officiel

    reg = registre_officiel()
    # touche FUNDING_JAMBE_NUE (« carry ») ET COPY_TRADING_NO_EDGE (« copier », « leader ») ;
    # « spot » ne rouvre QUE la zone funding.
    prop = "carry sur une jambe spot, en copiant les fills d'un leader"
    touchees = reg.consulter(prop)
    ids = {z.id for z in touchees}
    assert {"FUNDING_JAMBE_NUE", "COPY_TRADING_NO_EDGE"} <= ids, (
        "le test ne touche pas les 2 zones attendues (%s) : il ne prouverait rien" % sorted(ids)
    )
    motif = reg.refus(prop)
    assert motif, (
        "une proposition qui rouvre UNE zone (funding, via « spot ») mais reste en pleine zone "
        "COPY_TRADING a ete BLANCHIE : le registre s'auto-desarme de nouveau."
    )
    assert "COPY_TRADING_NO_EDGE" in motif


def test_un_carry_NON_COUVERT_est_marque_NON_COUVERT_dans_son_verdict():
    """🔴 MUTANT `False->True` SURVIVANT (funding_carry_economics.py:139).

    Sur le chemin de REFUS, le verdict porte `couvert=False`. Mute en `True`, le verdict d'une
    jambe **nue** annoncerait « couverte » -- et un dashboard qui lit ce champ afficherait une
    couverture qui n'existe pas. *Une donnee fabriquee presentee comme reelle : la seule chose que
    ce projet interdit absolument.*
    """
    v = evaluer_carry(
        funding_bps_h=5.0, bruit_prix_bps_h=200.0, cout_aller_retour_bps=12.0, couvert=False,
    )
    assert v.viable is False
    assert v.couvert is False, "une jambe NUE est annoncee COUVERTE dans son propre verdict"


def test_une_zone_sans_date_recoit_la_date_DU_JOUR_pas_une_chaine_vide():
    """🔴 MUTANT `Or->And` SURVIVANT (dead_zones.py:184).

    `date=str(date or datetime.now().date())` : si l'appelant ne fournit pas de date, on met
    CELLE DU JOUR. Mute en `and`, une zone sans date recevrait `"None"`.

    Ce n'est pas cosmetique : **une zone morte sans date n'est pas datable, donc pas
    re-examinable.** Tout le registre repose sur « qu'est-ce qui a change DEPUIS la mesure ? ».
    Aucun test ne passait par ce chemin : **toutes** nos zones fournissent une date explicite.
    """
    z = creer_zone_morte(
        id="SANS_DATE_EXPLICITE", hypothese="h", verdict="v", mesure="m", valeur=-1.0,
        unite="bps", echantillon=100, lecon="une regle generale",
        condition_de_reouverture="des donnees neuves", entree_mesuree="une_entree",
    )
    assert z.date and z.date != "None", "une zone morte sans date n'est pas re-examinable"
    assert len(z.date) == 10 and z.date.count("-") == 2, "format attendu AAAA-MM-JJ, recu %r" % z.date
