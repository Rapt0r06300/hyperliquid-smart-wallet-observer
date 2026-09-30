"""🔴 L'INCOHERENCE QUE FLO A VUE, ET QUE CE FICHIER REND IMPOSSIBLE (2026-07-13).

    « Pourtant ce sont toutes des decisions que TOI tu avais choisi de garder.
      Ce n'est pas coherent. »

Le meme jour, sur treize idees, j'ai applique DEUX standards opposes :

  * j'en ai ENTERRE six sans aucune mesure SUR ELLES, par extrapolation d'une mesure faite
    ailleurs ;
  * j'en ai GARDE sept en invoquant, la main sur le coeur, « pas de mesure = prejuge ».

Meme situation epistemique. Deux verdicts. Et le biais avait un SENS : enterrer RACCOURCIT la
liste. J'ai ete rigoureux la ou ca ne me coutait rien, et laxiste la ou ca me faisait gagner.

LA CAUSE TECHNIQUE : le registre refusait sur des MOTS-CLES. Or un mot-cle est une MENTION,
pas un MECANISME -- exactement le piege grep-vs-AST que j'ai corrige DEUX FOIS dans le code le
meme jour. Il etait aussi dans mon raisonnement, et je ne l'y ai pas vu.

LA REGLE, DESORMAIS EXECUTABLE :

    Une zone morte ne peut refuser une idee QUE si cette idee consomme
    LA MEME ENTREE que celle sur laquelle la mesure a ete faite.

Aucun ordre reel.
"""
from __future__ import annotations

import re

import pytest

from hl_observer.agent.dead_zones import (
    MIN_LONGUEUR_MOT_CLE,
    PreuveInsuffisante,
    creer_zone_morte,
)
from hl_observer.agent.dead_zones_hypersmart import ZONES, registre_officiel


# ============================================================ 0. 🔴 LE MOT-CLE MORT


def test_aucun_mot_cle_n_est_TROP_COURT_pour_pouvoir_matcher_un_jour():
    """🔴 TROUVE PAR UN TEST ROUGE, PAS PAR MOI (2026-07-13).

    `consulter()` extrait les mots par [a-z_]{3,}. Un mot-cle de MOINS de 3 caracteres ne peut
    donc **jamais** matcher. Il ne protege rien : il donne l'illusion d'une couverture.

    DEUX existaient, tranquillement, depuis des semaines :
        "rl" (zone ML sequentiel)  et  "mm" (zone market making).

    C'est la maladie du projet, une fois de plus : *une capacite presente, un chainon manquant,
    et personne qui se plaint.* Le fichier lui-meme mettait en garde contre les mots-cles morts
    -- deux lignes au-dessus de l'un d'eux.
    """
    morts = [
        (z.id, m)
        for z in ZONES
        for m in (z.mots_cles + z.mots_cles_reouverture)
        if len(m) < MIN_LONGUEUR_MOT_CLE
    ]
    assert not morts, (
        "mot(s)-cle(s) MORT(S) -- trop courts pour etre extraits par [a-z_]{%d,}, donc "
        "incapables de matcher quoi que ce soit : %s"
        % (MIN_LONGUEUR_MOT_CLE, ", ".join("%s:%r" % (i, m) for i, m in morts))
    )


def test_aucun_mot_cle_ne_contient_d_ESPACE_car_il_serait_mort_aussi():
    """Meme piege, autre forme : la regex coupe sur les espaces. Un mot-cle « suivi temps reel »
    ne peut jamais matcher. (Le fichier le disait deja en commentaire -- ce test le PROUVE.)"""
    morts = [
        (z.id, m)
        for z in ZONES
        for m in (z.mots_cles + z.mots_cles_reouverture)
        if " " in m or "-" in m
    ]
    assert not morts, "mot(s)-cle(s) MORT(S) (espace ou tiret) : %s" % morts


def test_un_mot_cle_doit_matcher_EXACTEMENT_ce_que_le_TOKENISEUR_extrait():
    """🔴 LA FORME GENERALE DU PIEGE (2026-07-13, 3e occurrence dans la journee).

    Les deux tests ci-dessus attrapaient la LONGUEUR, puis les ESPACES et TIRETS. Ils laissaient
    passer une 3e forme : **les CHIFFRES.** `consulter()` extrait les mots par `[a-z_]{3,}` --
    donc un mot-cle comme `"l3fifo"` est coupe par le tokeniseur en `"fifo"` : il ne peut
    **jamais** matcher, et il **passe les deux tests precedents**.

    *Corriger un symptome n'est pas soigner la maladie.* Ce test remet l'invariant sur la VRAIE
    regle : un mot-cle doit etre exactement ce que le tokeniseur sait produire.

    (Il rend les deux tests ci-dessus redondants -- on les GARDE : ils nomment le piege precis
    qu'ils ont attrape, et un test qui documente une erreur reelle vaut mieux qu'un test elegant.)
    """
    motif = re.compile(r"[a-z_]{%d,}$" % MIN_LONGUEUR_MOT_CLE)
    morts = [
        (z.id, m)
        for z in ZONES
        for m in (z.mots_cles + z.mots_cles_reouverture)
        if not motif.match(m)
    ]
    assert not morts, (
        "mot(s)-cle(s) INEXTRACTIBLE(S) -- le tokeniseur [a-z_]{%d,} ne les produira JAMAIS "
        "(chiffre, majuscule, accent, ponctuation...) : %s"
        % (MIN_LONGUEUR_MOT_CLE, ", ".join("%s:%r" % (i, m) for i, m in morts))
    )


# ============================================================ 1. TOUTE ZONE DECLARE SON ENTREE


def test_chaque_zone_morte_declare_l_entree_qu_elle_a_MESUREE():
    """Sans ce champ, un refus n'est qu'un mot-cle qui a matche."""
    for z in ZONES:
        assert z.entree_mesuree, (
            "la zone %s ne dit pas SUR QUELLE ENTREE elle a mesure : elle refuserait donc des "
            "idees dont sa mesure ne parle pas" % z.id
        )


def test_on_ne_PEUT_PAS_creer_une_zone_sans_entree_mesuree():
    """Le garde-fou doit MORDRE. Sinon il ne garde rien."""
    with pytest.raises(PreuveInsuffisante):
        creer_zone_morte(
            id="SANS_ENTREE", hypothese="h", verdict="v", mesure="m", valeur=-1.0,
            unite="bps", echantillon=100, lecon="une regle generale",
            condition_de_reouverture="des donnees neuves",
            entree_mesuree="",                      # <-- la faute
            mots_cles=("truc",),
        )


# ============================================================ 2. LES DEUX ENTERREMENTS LEGITIMES


@pytest.mark.parametrize("proposition", [
    "entrainer un LSTM sur les sequences de fills du leader",
    "un transformer avec attention sur le signal de copy",
])
def test_LSTM_et_TRANSFORMER_restent_REFUSES_car_MEME_entree(proposition):
    """IDEA-02 / IDEA-03. Ces modeles lisent le fill public d'un leader -- exactement l'entree
    mesuree a -7,97 bps. Le refus est une DEDUCTION, pas un prejuge : meme entree, autre
    fonction. *Un modele n'invente pas d'information : il en extrait.*"""
    ex = registre_officiel().examiner(proposition, entree="fill_public_leader")
    assert ex.refuse, "%s aurait du etre refuse (meme entree que la mesure)" % proposition


# ============================================================ 3. 🔴 LES DEUX QUE J'AI EXHUMES


def test_le_RL_de_SORTIE_ne_peut_PLUS_etre_refuse_par_la_mesure_du_signal_D_ENTREE():
    """🔴 IDEA-04, EXHUMEE.

    La mesure « -7,97 bps » porte sur le FILL PUBLIC D'UN LEADER : elle dit que le signal
    d'ENTREE ne predit rien. Une politique de SORTIE ne lit PAS ce signal : elle lit l'etat de la
    position APRES l'entree (prix parcouru, temps ecoule, vol courante).

    Une mesure faite sur une autre entree ne tue pas cette idee : ELLE N'EN PARLE PAS.

    J'avais quand meme enterre IDEA-04, en empilant un second argument (« le gain de sortie est
    deja pris par le correctif du breakeven »). C'est peut-etre vrai -- mais ce n'est PAS ce que
    la mesure dit, et je l'ai presente comme tel. Ce test m'interdit de recommencer.

    🚩 ET SA 1re VERSION A ETE ROUGE POUR UNE AUTRE RAISON QUE CELLE QUE JE CROYAIS : elle disait
    « agent RL », et le registre a repondu **LIBRE** -- pas parce qu'il etait d'accord avec moi,
    mais parce que le mot-cle "rl" faisait DEUX caracteres et ne pouvait matcher JAMAIS.
    *J'ai eu raison sur la conclusion, et tort sur le mecanisme.* Le test dit maintenant
    « reinforcement », qui touche VRAIMENT la zone -- pour prouver que c'est bien l'ENTREE, et
    non un trou dans le filtre, qui degrade le refus en question.
    """
    ex = registre_officiel().examiner(
        "un modele de reinforcement learning qui apprend la politique de sortie "
        "(quand couper, quand laisser courir)",
        entree="etat_de_la_position_apres_entree",
    )
    assert ex.statut == "A_EXAMINER", (
        "le RL de SORTIE ne consomme PAS le fill du leader : aucune de nos mesures ne le tue. "
        "statut obtenu : %s" % ex.statut
    )
    assert "ENTREE_DIFFERENTE" in ex.motif
    # et la zone a bien ETE touchee : ce n'est pas un trou dans le filtre.
    assert "ML_SEQUENTIEL_SUR_SIGNAL_SANS_INFORMATION" in ex.zones


def test_identifier_la_CONTREPARTIE_de_notre_fill_ne_peut_PLUS_etre_refuse():
    """🔴 IDEA-47, EXHUMEE -- et pour une raison que j'avais ecrasee.

    « Suivre les market makers connus » a DEUX lectures, et j'ai enterre les deux d'un coup :

      (a) COPIER les fills d'un MM  -> c'est du copy-trading. Mort. Meme entree. OK.
      (b) savoir QUI est en face de NOTRE fill -> c'est un predicteur de SELECTION ADVERSE
          (markout). L'entree n'est pas le fill d'un leader : c'est la contrepartie du NOTRE.
          **Cette entree n'a JAMAIS ete mesuree.**

    J'ai collapse (b) dans (a) parce que le mot-cle « market_makers » matchait. Le mot-cle avait
    raison sur la lettre, et tort sur le mecanisme.
    """
    ex = registre_officiel().examiner(
        "identifier si la contrepartie de notre propre fill est un market maker toxique",
        entree="contrepartie_de_notre_fill",
    )
    assert ex.statut == "A_EXAMINER", (
        "savoir QUI est en face de NOTRE fill n'est pas copier le fill d'un leader. "
        "statut obtenu : %s" % ex.statut
    )


# ============================================================ 4. LE DENY-BY-DEFAULT TIENT TOUJOURS


def test_sans_entree_declaree_le_registre_REFUSE_toujours():
    """⚠️ Le correctif ne doit pas devenir une PORTE DE SORTIE.

    Si personne ne declare d'entree, on retombe sur le comportement historique : mot-cle touche =
    refus. On ne relache RIEN par omission. Il faut un acte POSITIF (declarer une entree que la
    mesure n'a jamais consommee) pour transformer un refus en question.
    """
    ex = registre_officiel().examiner("relancer un scanner de wallets pour copier les meilleurs")
    assert ex.refuse
    assert "COPY_TRADING_NO_EDGE" in ex.motif


def test_declarer_une_entree_BIDON_ne_blanchit_pas_l_idee_mais_la_MARQUE():
    """Et si quelqu'un declare une entree fantaisiste pour contourner le registre ?

    Il n'obtient PAS un feu vert : il obtient A_EXAMINER, avec le nom des zones touchees et
    l'entree qu'elles ont reellement mesuree. La question devient VISIBLE au lieu d'etre
    silencieuse. *Un registre honnete ne cache ni ses refus, ni ses doutes.*
    """
    ex = registre_officiel().examiner(
        "copier les fills des leaders", entree="entree_magique_inventee",
    )
    assert ex.statut == "A_EXAMINER"
    assert "COPY_TRADING_NO_EDGE" in ex.motif
    assert "fill_public_leader" in ex.motif      # la vraie entree mesuree est CITEE
    assert not ex.refuse
