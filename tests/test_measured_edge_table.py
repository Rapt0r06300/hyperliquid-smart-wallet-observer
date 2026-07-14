"""Q1 -- LA TABLE D'EDGE MESUREE. Ce qu'elle doit REFUSER compte plus que ce qu'elle rend.

Le bug d'origine tient en une ligne (`fresh_opportunity.py:342`) :

    return 14.0 + score * 0.55 + wallets * 9.0 + notional / 25000 + tightness * 10

Huit constantes inventees, qui produisent l'edge BRUT de toute la chaine. Ces tests defendent
la seule alternative honnete : le markout REELLEMENT observe, une borne basse, et un refus des
qu'on ne sait pas.

Aucun ordre reel.
"""
from __future__ import annotations

import math

import pytest

from hl_observer.edge.measured_edge_table import (
    EDGE_BUCKET_VIDE,
    EDGE_FEATURES_INCOMPLETES,
    EDGE_MESURE_OK,
    EDGE_TABLE_ABSENTE,
    EDGE_TABLE_LOOKAHEAD,
    Features,
    Observation,
    TableEdgeMesuree,
    construire,
    markout_bps,
    sens_du_trade,
)


def _f(**kw) -> Features:
    base = dict(strategie="COPY", coin="BTC", direction="LONG",
                signal_age_ms=500.0, leader_score=70.0, consensus_wallets=2.0)
    base.update(kw)
    return Features(**base)  # type: ignore[arg-type]


def _obs(markout: float, ms: float = 1000.0, **kw) -> Observation:
    return Observation(features=_f(**kw), markout_bps=markout, signal_ms=ms)


# ====================================================== LE MARKOUT (l'unique edge honnete)


def test_le_markout_est_le_mouvement_REEL_du_prix_dans_le_sens_du_trade():
    # LONG, le prix monte de 1 % -> +100 bps pour nous
    assert markout_bps(mid_entree=100.0, mid_futur=101.0, direction="LONG") == pytest.approx(100.0)
    # SHORT, le prix monte de 1 % -> -100 bps pour nous. Le signe compte.
    assert markout_bps(mid_entree=100.0, mid_futur=101.0, direction="SHORT") == pytest.approx(-100.0)
    # SHORT, le prix baisse -> on gagne
    assert markout_bps(mid_entree=100.0, mid_futur=99.0, direction="SHORT") == pytest.approx(100.0)


def test_un_markout_IMPOSSIBLE_rend_None_et_JAMAIS_zero():
    """None ('je ne sais pas') != 0.0 ('le prix n'a pas bouge').

    Les confondre, c'est fabriquer une donnee : un zero se propage dans les moyennes comme une
    observation reelle. C'est exactement le genre de mensonge que ce module existe pour tuer.
    """
    assert markout_bps(mid_entree=0.0, mid_futur=101.0, direction="LONG") is None
    assert markout_bps(mid_entree=100.0, mid_futur=0.0, direction="LONG") is None
    assert markout_bps(mid_entree=100.0, mid_futur=101.0, direction="PEUT_ETRE") is None
    assert markout_bps(mid_entree=None, mid_futur=101.0, direction="LONG") is None  # type: ignore[arg-type]


def test_un_sens_indechiffrable_vaut_REFUS_pas_LONG_par_defaut():
    assert sens_du_trade("long") == 1
    assert sens_du_trade("SELL") == -1
    assert sens_du_trade("") == 0
    assert sens_du_trade(None) == 0
    assert sens_du_trade("peut-etre") == 0


# ====================================================== LA BORNE BASSE (le coeur du sujet)


def test_on_rend_la_BORNE_BASSE_pas_la_MOYENNE():
    """Une moyenne de +50 bps sur des observations tres dispersees n'est pas un edge.

    La borne basse (moyenne - 1,96 x erreur standard) le dit toute seule : elle plonge sous zero
    des que le bruit domine. C'est ce qui empeche d'appeler « edge » un coup de chance.
    """
    # 40 observations centrees sur +50 bps mais TRES bruitees (+-300 bps)
    obs = []
    for i in range(40):
        obs.append(_obs(50.0 + (300.0 if i % 2 else -300.0)))
    t = construire(obs, horizon_ms=60_000, min_echantillons=10)

    r = t.chercher(_f(), signal_ms=999_999)
    assert r.mesure
    assert r.moyenne_bps == pytest.approx(50.0, abs=1e-6)   # la moyenne est BELLE
    assert r.edge_brut_bps is not None
    assert r.edge_brut_bps < 0.0                            # la borne basse dit la VERITE
    assert r.edge_brut_bps < r.moyenne_bps


def test_un_edge_REEL_et_STABLE_survit_a_la_borne_basse():
    """Symetrie : la borne basse ne doit pas tout tuer, sinon elle rend un PnL de zero et on se
    croit prudent. Un edge net, repete, peu bruite, DOIT passer."""
    obs = [_obs(20.0 + (1.0 if i % 2 else -1.0)) for i in range(60)]
    t = construire(obs, horizon_ms=60_000, min_echantillons=10)
    r = t.chercher(_f(), signal_ms=999_999)
    assert r.mesure
    assert r.edge_brut_bps is not None
    assert r.edge_brut_bps > 19.0     # ~20 bps, l'incertitude est minuscule


def test_UNE_seule_observation_ne_fait_JAMAIS_un_edge():
    """n=1 -> erreur standard infinie -> borne basse = -inf. Et de toute facon min_echantillons
    l'ecarte. Deux verrous, parce qu'un seul coup de chance ne doit jamais devenir une these."""
    t = construire([_obs(500.0)], horizon_ms=60_000, min_echantillons=1)
    c = t.cellules[_f().cles()[0]]
    assert c.n == 1
    assert c.moyenne_bps == pytest.approx(500.0)
    assert c.borne_basse_bps == float("-inf")


# ====================================================== LE REFUS (deny-by-default)


def test_un_bucket_SANS_ASSEZ_D_ECHANTILLONS_refuse_et_ne_rend_PAS_une_valeur_par_defaut():
    """LE test central de Q1. Pas de donnee = pas de trade. Pas de moyenne globale de secours,
    pas de zero, pas de 14.0. `None`, et un code de refus."""
    t = construire([_obs(30.0) for _ in range(5)], horizon_ms=60_000, min_echantillons=30)
    r = t.chercher(_f(), signal_ms=999_999)
    assert not r.mesure
    assert r.edge_brut_bps is None
    assert r.raison == EDGE_BUCKET_VIDE


def test_une_table_VIDE_refuse_tout():
    t = TableEdgeMesuree(horizon_ms=60_000, construite_jusqu_a_ms=0, min_echantillons=30, z=1.96)
    r = t.chercher(_f(), signal_ms=999_999)
    assert not r.mesure and r.edge_brut_bps is None and r.raison == EDGE_TABLE_ABSENTE


def test_un_coin_JAMAIS_VU_ne_prend_pas_l_edge_d_un_autre_coin():
    """🚩 CE TEST DISAIT UNE CHOSE ET EN CERTIFIAIT UNE AUTRE (corrige le 13/07, trouve par G2).

    Son NOM dit « un coin jamais vu ne prend pas l'edge d'un autre ». Son CORPS assertait
    `r.mesure is True` -- c'est-a-dire que DOGE prenait bel et bien l'edge de BTC, juste etiquete
    « large ». Le nom etait l'intention ; le corps certifiait le bug. Et le nom m'a berce.

    La cellule LARGE (`STRAT|*|...`) est une GENERALISATION. Nourrie par UN SEUL marche, elle ne
    generalise rien : c'est BTC qui porte un masque. Un marche jamais mesure en heriterait l'edge
    -- exactement la maladie de P2-2 (couts constants d'un coin a l'autre), revenue par la porte
    de l'EDGE.

    Regle : une cellule large exige >= MIN_COINS_POUR_LARGE marches DISTINCTS, sinon elle n'est
    pas emise du tout, et l'interrogation tombe en REFUS.
    """
    # 50 observations, UN SEUL coin -> aucune cellule large ne doit sortir.
    t = construire([_obs(30.0, coin="BTC") for _ in range(50)], horizon_ms=60_000, min_echantillons=30)
    r = t.chercher(_f(coin="DOGE"), signal_ms=999_999)
    assert not r.mesure, "DOGE herite de l'edge de BTC via une cellule large mono-coin"
    assert r.raison == EDGE_BUCKET_VIDE
    assert r.edge_brut_bps is None, "un edge rendu ici serait l'edge d'un AUTRE marche"

    # BTC lui-meme, en revanche, reste mesure : c'est sa cellule FINE, elle est legitime.
    assert t.chercher(_f(coin="BTC"), signal_ms=999_999).niveau == "fin"


def test_la_cellule_LARGE_existe_des_qu_assez_de_MARCHES_l_ont_nourrie():
    """Le niveau large n'est pas supprime -- il est CONDITIONNE. Avec assez de marches distincts,
    il generalise vraiment, et il le DIT (`niveau == 'large'`)."""
    coins = ["BTC", "ETH", "SOL", "DOGE", "HYPE", "AVAX"]     # 6 >= MIN_COINS_POUR_LARGE (5)
    obs = [_obs(30.0, coin=c) for c in coins for _ in range(10)]
    t = construire(obs, horizon_ms=60_000, min_echantillons=30)

    r = t.chercher(_f(coin="UN_COIN_JAMAIS_VU"), signal_ms=999_999)
    assert r.mesure
    assert r.niveau == "large", "un edge issu du niveau large doit le DIRE"
    assert r.n == 60

    # et si le large est vide aussi (autre strategie), refus net
    r2 = t.chercher(_f(coin="DOGE", strategie="ARBITRAGE"), signal_ms=999_999)
    assert not r2.mesure and r2.raison == EDGE_BUCKET_VIDE


def test_le_niveau_utilise_est_TOUJOURS_dit():
    """Une cascade silencieuse vers un chiffre plus vague, c'est un mensonge poli. Le resultat
    porte `niveau` et `n` : on sait toujours SUR QUOI on a decide."""
    t = construire([_obs(30.0) for _ in range(50)], horizon_ms=60_000, min_echantillons=30)
    r = t.chercher(_f(), signal_ms=999_999)
    assert r.niveau == "fin"
    assert "BTC" in r.cle
    assert r.n == 50


def test_un_sens_indechiffrable_est_REFUSE_par_la_table():
    t = construire([_obs(30.0) for _ in range(50)], horizon_ms=60_000, min_echantillons=10)
    r = t.chercher(_f(direction="???"), signal_ms=999_999)
    assert not r.mesure and r.raison == EDGE_FEATURES_INCOMPLETES


# ====================================================== L'ANTI-LOOKAHEAD


def test_interroger_la_table_sur_un_signal_QU_ELLE_A_VU_est_REFUSE():
    """LE bug n°1 de tous les backtests, rendu impossible.

    La table est construite sur des signaux jusqu'a T. Interroger un signal a T-10, c'est lui
    demander « qu'est-ce que le prix a fait apres ce signal ? » alors qu'elle a DEJA la reponse
    dans ses moyennes. L'edge devient une prophetie auto-realisatrice.
    """
    t = construire([_obs(30.0, ms=1_000_000.0) for _ in range(50)],
                   horizon_ms=60_000, min_echantillons=10)
    assert t.construite_jusqu_a_ms == 1_000_000

    # un signal ANTERIEUR ou EGAL -> la table a vu son futur -> REFUS
    assert t.chercher(_f(), signal_ms=999_999).raison == EDGE_TABLE_LOOKAHEAD
    assert t.chercher(_f(), signal_ms=1_000_000).raison == EDGE_TABLE_LOOKAHEAD
    # un signal POSTERIEUR -> legitime
    assert t.chercher(_f(), signal_ms=1_000_001).mesure


def test_sans_horodatage_de_signal_on_ne_verifie_PAS_le_lookahead_mais_on_ne_ment_pas():
    """`signal_ms=None` = usage hors-ligne (analyse, tests). En production l'appelant DOIT le
    fournir -- c'est teste au point de branchement, pas ici."""
    t = construire([_obs(30.0, ms=1_000_000.0) for _ in range(50)],
                   horizon_ms=60_000, min_echantillons=10)
    assert t.chercher(_f(), signal_ms=None).mesure


# ====================================================== PERSISTANCE


def test_aller_retour_json_conserve_le_verdict():
    t = construire([_obs(20.0 + i * 0.1, ms=5_000.0) for i in range(50)],
                   horizon_ms=60_000, min_echantillons=10)
    t2 = TableEdgeMesuree.depuis_json(t.vers_json())
    a = t.chercher(_f(), signal_ms=9_999_999)
    b = t2.chercher(_f(), signal_ms=9_999_999)
    assert (a.mesure, a.niveau, a.n) == (b.mesure, b.niveau, b.n)
    assert a.edge_brut_bps == pytest.approx(b.edge_brut_bps or 0.0, abs=1e-6)
    assert t2.construite_jusqu_a_ms == 5_000


def test_la_table_declare_sa_SOURCE_et_ne_melange_pas_les_mondes():
    """CLAUDE.md : LIVE / BACKTEST / REPLAY / TEST_FIXTURE ne se melangent jamais."""
    t = construire([_obs(10.0)], horizon_ms=1, source="TEST_FIXTURE")
    assert t.source == "TEST_FIXTURE"
    assert TableEdgeMesuree.depuis_json(t.vers_json()).source == "TEST_FIXTURE"


def test_un_markout_non_fini_est_IGNORE_et_ne_pollue_pas_la_moyenne():
    obs = [_obs(10.0) for _ in range(10)]
    obs.append(Observation(features=_f(), markout_bps=float("nan"), signal_ms=1.0))
    obs.append(Observation(features=_f(), markout_bps=float("inf"), signal_ms=1.0))
    t = construire(obs, horizon_ms=1, min_echantillons=5)
    c = t.cellules[_f().cles()[0]]
    assert c.n == 10
    assert math.isfinite(c.moyenne_bps)
    assert c.moyenne_bps == pytest.approx(10.0)
