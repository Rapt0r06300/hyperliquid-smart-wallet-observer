"""L'AGENT AUTO-AMELIORANT, REPRODUIT ET TESTE (2026-07-12).

Framework de l'article Horizon (« How Quants Build Trading Agents That Improve Themselves ») :

    generateur -> evaluateur -> selecteur, avec MEMOIRE et VERIFICATEUR SEPARE.

Ce qu'on avait deja : la boucle (scenario_grid + 150M scenarios + gate OOS).
Ce qui MANQUAIT, et que ces tests gardent :

  1. la MEMOIRE des echecs (fail -> investigate -> distil -> consult) ;
  2. le score COMPOSITE (« score raw returns and it will find the most overfit curve ») ;
  3. le HOLDOUT SCELLE (« the agent never grades its own work »).

Et la verite que l'article ne dit pas : une boucle de recherche ne CREE pas un edge.
150 millions de scenarios -> robust_count = 0. L'espace du copy-trading est vide.

Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.agent.dead_zones import (
    MIN_ECHANTILLON,
    PreuveInsuffisante,
    RegistreZonesMortes,
    creer_zone_morte,
)
from hl_observer.agent.dead_zones_hypersmart import registre_officiel
from hl_observer.agent.fitness import (
    DRAWDOWN_MAX_PCT,
    MOTIF_DD,
    MOTIF_N,
    MOTIF_PF,
    MOTIF_STABILITE,
    PF_MIN,
    evaluer,
    profit_factor,
)
from hl_observer.agent.improvement_loop import BoucleAmelioration
from hl_observer.agent.sealed_verifier import (
    MOTIF_DEJA_OUVERT,
    MOTIF_ECHEC_HOLDOUT,
    HoldoutViole,
    VerificateurScelle,
)


def _zone(id="Z", **kw):
    base = dict(
        hypothese="h", verdict="v", mesure="m", valeur=-1.0, unite="bps",
        echantillon=100, lecon="une regle generale",
        condition_de_reouverture="des donnees neuves",
        entree_mesuree="une_entree_de_test",
        mots_cles=("truc",),
    )
    base.update(kw)
    return creer_zone_morte(id=id, **base)


def _gagnant(n=60):
    """PF ~2, drawdown faible : le profil d'une strategie qui tient."""
    return [3.0 if i % 3 else -3.0 for i in range(n)]


def _fenetres_stables():
    return [[3.0, 3.0, -1.0]] * 4


# =============================================================================================
# 1. LA MEMOIRE — « sans elle, l'agent re-propose ce qu'il a deja rejete »
# =============================================================================================

def test_a_proposal_that_falls_in_a_DEAD_ZONE_is_refused_with_its_PROOF():
    """LE TEST QUI COMPTE. J'ai passe des sessions a regler `min_edge` sur un edge FABRIQUE.
    Le registre rend ca impossible : la proposition est refusee, avec le chiffre qui l'a tuee."""
    r = registre_officiel()
    refus = r.refus("optimiser le seuil min_edge du sniper pour plus de trades")
    assert "COPY_TRADING_NO_EDGE" in refus
    assert "-7.97" in refus                    # la preuve chiffree, dans le refus
    assert "24133" in refus.replace(" ", "")   # l'echantillon


def test_the_registry_blocks_EVERY_dead_end_we_have_already_paid_for():
    r = registre_officiel()
    for prop, zone in (
        ("baisser le funding threshold", "FUNDING_JAMBE_NUE"),
        ("reactiver le bus github externe", "BUS_GITHUB_EXTERNE"),
        ("faire du market making sur BTC", "MM_SUR_LES_MAJORS"),
        ("recalibrer le sltp avec un nouveau grid", "CALIBRAGE_SLTP_OOS"),
        ("aller plus vite, reduire la latence du hot path", "LATENCE_NEST_PAS_LE_PROBLEME"),
    ):
        assert zone in r.refus(prop), "la zone %s ne protege pas contre : %s" % (zone, prop)


def test_a_LIVE_path_is_never_blocked():
    """Le registre ne doit pas devenir un dogme qui interdit tout. La piste vivante passe."""
    r = registre_officiel()
    assert r.refus("mesurer le flux de trades sur les marches fins") == ""


def test_a_dead_zone_WITHOUT_a_measurement_is_REFUSED():
    """DENY-BY-DEFAULT SYMETRIQUE : une hypothese sans preuve chiffree est un PREJUGE.
    Le registre refuse de l'enterrer -- sinon il interdirait des pistes pour de mauvaises raisons."""
    with pytest.raises(PreuveInsuffisante):
        _zone(echantillon=MIN_ECHANTILLON - 1)


def test_a_dead_zone_MUST_say_what_would_REOPEN_it():
    """Une impasse definitive est un dogme, pas une mesure. Le marche change."""
    with pytest.raises(PreuveInsuffisante):
        _zone(condition_de_reouverture="")


def test_a_dead_zone_MUST_distil_a_GENERAL_lesson_not_an_anecdote():
    with pytest.raises(PreuveInsuffisante):
        _zone(lecon="")


def test_a_zone_can_be_REOPENED_but_never_in_silence():
    r = RegistreZonesMortes()
    r.enterrer(_zone("Z1"))
    with pytest.raises(PreuveInsuffisante):
        r.exhumer("Z1", raison="")
    assert r.exhumer("Z1", raison="nouvelles donnees sur 6 mois, autre regime") is True
    assert r.refus("truc") == ""


def test_the_registry_survives_a_round_trip_to_disk(tmp_path):
    r = registre_officiel()
    f = tmp_path / "z.json"
    r.sauver(str(f))
    r2 = RegistreZonesMortes.charger(str(f))
    assert len(r2.zones) == len(r.zones)
    assert "COPY_TRADING_NO_EDGE" in r2.refus("min_edge du copy")


def test_a_missing_registry_is_an_HONEST_EMPTY_state_not_a_crash(tmp_path):
    r = RegistreZonesMortes.charger(str(tmp_path / "inexistant.json"))
    assert r.zones == []


# =============================================================================================
# 2. LE SCORE — « the scoring rule IS the strategy »
# =============================================================================================

def test_the_score_is_a_VETO_not_an_average():
    """LE PIEGE DU SCORE COMPOSITE. Un PF de reve ne doit PAS racheter un drawdown mortel.
    Une moyenne le permettrait. Un veto, non."""
    # PF = 4000/1500 = 2,67 -- superbe. Mais le creux depuis le sommet fait 30 %.
    # Une moyenne dirait "bon score, leger bemol". Un veto dit ZERO.
    ruine = [100.0] * 40 + [-1500.0]
    f = evaluer(ruine, fenetres=_fenetres_stables())
    assert f.profit_factor > 2.0             # le PF est SUPERBE
    assert f.drawdown_pct > DRAWDOWN_MAX_PCT # et pourtant on refuse
    assert f.accepte is False
    assert MOTIF_DD in f.motifs_de_rejet
    assert f.score == 0.0                    # ZERO. Pas "un peu moins bien".


def test_a_89_percent_WINRATE_that_LOSES_money_is_rejected():
    """MESURE REELLE (session du 08/07) : 17 gains, 2 pertes -> winrate 89 %... et PnL negatif.
    Le winrate est un mensonge confortable. Le profit factor, non."""
    pnls = [0.30] * 17 + [-3.0, -3.0]
    assert profit_factor(pnls) < 1.0
    f = evaluer(pnls * 2, fenetres=_fenetres_stables())
    assert f.accepte is False
    assert MOTIF_PF in f.motifs_de_rejet


def test_three_lucky_trades_are_NOT_a_strategy():
    f = evaluer([10.0, 10.0, 10.0], fenetres=_fenetres_stables())
    assert f.accepte is False
    assert MOTIF_N in f.motifs_de_rejet


def test_a_config_that_wins_on_ONE_window_only_has_MEMORISED_it():
    """C'est le surajustement, vu de face. Une seule fenetre gagnante = memorisation."""
    f = evaluer(_gagnant(), fenetres=[[5.0], [-5.0], [-5.0], [-5.0]])
    assert f.accepte is False
    assert MOTIF_STABILITE in f.motifs_de_rejet


def test_no_windows_at_all_means_NO_stability_proof_so_REJECT():
    """Deny-by-default : sans preuve de stabilite, pas de benefice du doute."""
    f = evaluer(_gagnant(), fenetres=None)
    assert f.accepte is False
    assert MOTIF_STABILITE in f.motifs_de_rejet


def test_a_robust_config_IS_accepted():
    """Le score n'est pas un refus de principe : une config solide passe."""
    f = evaluer(_gagnant(), fenetres=_fenetres_stables())
    assert f.accepte is True
    assert f.profit_factor >= PF_MIN
    assert f.drawdown_pct <= DRAWDOWN_MAX_PCT
    assert f.score > 0


def test_empty_data_scores_ZERO_never_infinity():
    assert evaluer([]).score == 0.0


# =============================================================================================
# 3. LE HOLDOUT SCELLE — « the agent never grades its own work »
# =============================================================================================

def test_reading_the_holdout_during_SELECTION_raises():
    """LE VERROU. Aujourd'hui rien n'EMPECHE de selectionner sur le holdout : c'est une
    convention. Les conventions ne survivent pas a une session de 3 h ou l'on veut
    desesperement un chiffre positif."""
    v = VerificateurScelle(_holdout=_gagnant())
    assert v.scelle is True
    with pytest.raises(HoldoutViole):
        v.lire_holdout_pendant_selection()


def test_the_holdout_opens_ONCE_and_only_once():
    """Regarder le holdout deux fois, c'est le SELECTIONNER. Il n'est alors plus un holdout :
    c'est du train qui s'ignore."""
    v = VerificateurScelle(_holdout=_gagnant(), _fenetres_holdout=_fenetres_stables())
    r1 = v.juger("A", train=_gagnant(), validation=_gagnant(),
                 fenetres_train=_fenetres_stables(), fenetres_validation=_fenetres_stables())
    assert r1.promu is True
    assert "UNIQUE ET DEFINITIF" in r1.ouverture_holdout

    r2 = v.juger("B", train=_gagnant(), validation=_gagnant(),
                 fenetres_train=_fenetres_stables(), fenetres_validation=_fenetres_stables())
    assert r2.promu is False
    assert MOTIF_DEJA_OUVERT in r2.motifs


def test_a_TRAIN_MIRAGE_dies_on_the_holdout():
    """CE QUI NOUS EST ARRIVE. 150 millions de scenarios : superbes sur train, morts sur holdout.
    robust_count = 0. La boucle avait raison -- c'est nous qui aurions pu nous mentir."""
    v = VerificateurScelle(_holdout=[-5.0] * 60, _fenetres_holdout=[[-5.0]] * 4)
    r = v.juger("mirage", train=_gagnant(), validation=_gagnant(),
                fenetres_train=_fenetres_stables(), fenetres_validation=_fenetres_stables())
    assert r.promu is False
    assert MOTIF_ECHEC_HOLDOUT in r.motifs


def test_the_holdout_is_NOT_burned_on_a_candidate_that_already_failed_train():
    """Economique autant qu'honnete : un candidat rejete sur train ne touche pas au holdout."""
    v = VerificateurScelle(_holdout=_gagnant())
    r = v.juger("nul", train=[-1.0] * 60, validation=_gagnant())
    assert r.holdout is None
    assert v.scelle is True                   # le scelle est INTACT


def test_resealing_requires_NEW_data_and_a_written_reason():
    v = VerificateurScelle(_holdout=_gagnant())
    with pytest.raises(HoldoutViole):
        v.sceller_a_nouveau(nouveau_holdout=_gagnant(), raison="")
    with pytest.raises(HoldoutViole):
        v.sceller_a_nouveau(nouveau_holdout=[], raison="parce que")


# =============================================================================================
# 4. LA BOUCLE COMPLETE
# =============================================================================================

def test_the_loop_SKIPS_proposals_that_are_already_dead():
    """L'economie de la memoire, mesuree : les impasses connues ne coutent PAS un backtest."""
    b = BoucleAmelioration(
        registre=registre_officiel(),
        verificateur=VerificateurScelle(_holdout=_gagnant(), _fenetres_holdout=_fenetres_stables()),
        evaluer_sur_train=lambda _: (_gagnant(), _fenetres_stables()),
        evaluer_sur_validation=lambda _: (_gagnant(), _fenetres_stables()),
    )
    r = b.tourner([
        "optimiser min_edge du copy",          # zone morte
        "reactiver le bus github",             # zone morte
        "mesurer le flux sur marches fins",    # LIBRE
    ])
    assert r.economisees_par_memoire == 2
    assert r.evaluees == 1
    assert r.verdict_final is not None and r.verdict_final.promu is True


def test_the_loop_can_BURY_a_new_failure_with_its_proof():
    """`distil` : un echec devient une REGLE, pas une anecdote. Et il protege les runs suivants."""
    reg = RegistreZonesMortes()
    b = BoucleAmelioration(
        registre=reg, verificateur=VerificateurScelle(_holdout=_gagnant()),
        evaluer_sur_train=lambda _: (_gagnant(), _fenetres_stables()),
        evaluer_sur_validation=lambda _: (_gagnant(), _fenetres_stables()),
    )
    assert b.enterrer_lechec(
        id="NOUVELLE_IMPASSE", hypothese="h", verdict="mort",
        mesure="edge net", valeur=-4.0, unite="bps", echantillon=500,
        lecon="une regle generale", condition_de_reouverture="des donnees neuves",
        entree_mesuree="une_entree_de_test",
        mots_cles=("impasse",),
    ) is True
    assert "NOUVELLE_IMPASSE" in reg.refus("tester encore cette impasse")


def test_the_loop_NEVER_promises_it_can_create_an_edge():
    """LA VERITE QUE L'ARTICLE NE DIT PAS. Une boucle TROUVE un edge s'il existe.
    Elle n'en FAIT PAS EXISTER un. 150M de scenarios -> robust_count = 0."""
    b = BoucleAmelioration(
        registre=RegistreZonesMortes(), verificateur=VerificateurScelle(_holdout=_gagnant()),
        evaluer_sur_train=lambda _: ([], []),
        evaluer_sur_validation=lambda _: ([], []),
    )
    r = b.tourner(["n'importe quoi"]).as_dict()
    assert "ne CREE pas un edge" in r["avertissement"]
    assert "robust_count = 0" in r["avertissement"]
    assert r["real_execution"] is False
