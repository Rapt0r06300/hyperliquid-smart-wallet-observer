"""Scoring point-in-time des wallets et rotation des 10 slots premium.

Deux tests portent tout le reste : `test_un_wallet_tres_rentable_mais_incopiable_nest_pas_eligible`
(on classe sur l'edge copiable après NOS coûts, pas sur le PnL du leader) et
`test_lhysteresis_empeche_de_permuter_pour_du_bruit`.

Paper only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.following import wallet_scoring_shortlist as WS  # noqa: E402

T0 = 1_700_000_000_000
H = 1000


def _eps(n, markout_bps, *, horizon=H, notional=500.0, t0=T0):
    return [{"ts_ms": t0 + i * 1_000, "notional_usd": notional,
             "markouts_bps": {horizon: markout_bps}} for i in range(n)]


def _score(episodes, *, cout=9.0, as_of=None, min_eps=20):
    return WS.score_point_in_time(episodes, as_of_ms=as_of or (T0 + 10_000_000),
                                  cout_ar_bps=cout, horizon_markout_ms=H, min_episodes=min_eps)


# ═══════════════ le score est CE QUI NOUS REVIENT ═══════════════
def test_un_wallet_tres_rentable_mais_incopiable_nest_pas_eligible():
    """+5 bps de markout, mais 9 bps de coûts : son PnL n'est pas le nôtre."""
    s = _score(_eps(30, 5.0), cout=9.0)
    assert s["statut"] == "MESURE"
    assert s["score_copyable_bps"] == -4.0 and s["eligible_core"] is False


def test_un_wallet_copiable_est_eligible():
    s = _score(_eps(30, 20.0), cout=9.0)
    assert s["score_copyable_bps"] == 11.0 and s["eligible_core"] is True
    assert s["hit_rate"] == 1.0 and s["profit_factor"] is None      # aucune perte : PF non defini


def test_le_cout_est_soustrait_episode_par_episode():
    s = _score(_eps(25, 12.0), cout=4.5)
    assert s["score_copyable_bps"] == 7.5 and s["net_total_bps"] == 187.5


# ═══════════════ point-in-time ═══════════════
def test_aucun_episode_posterieur_a_as_of_nest_compte():
    episodes = _eps(30, 20.0)
    s = WS.score_point_in_time(episodes, as_of_ms=T0 + 9_000, cout_ar_bps=9.0,
                               horizon_markout_ms=H, min_episodes=5)
    assert s["n_episodes_vus"] == 10          # 0..9 s inclus, le futur est invisible
    assert s["n_mesurables"] == 10


def test_la_recence_est_mesuree_depuis_as_of():
    s = WS.score_point_in_time(_eps(25, 20.0), as_of_ms=T0 + 100_000, cout_ar_bps=9.0,
                               horizon_markout_ms=H, min_episodes=5)
    assert s["recence_ms"] == 100_000 - 24_000


# ═══════════════ deny-by-default ═══════════════
def test_sans_markout_le_wallet_na_pas_de_score_et_nest_pas_note_zero():
    episodes = [{"ts_ms": T0 + i, "notional_usd": 100.0} for i in range(50)]
    s = _score(episodes)
    assert s["score_copyable_bps"] is None and s["statut"] == "NON_MESURE"
    assert s["eligible_core"] is False and s["n_sans_markout"] == 50


def test_echantillon_trop_petit_ne_produit_aucun_score():
    s = _score(_eps(5, 50.0))
    assert s["statut"] == "NON_MESURE" and s["score_copyable_bps"] is None


def test_un_markout_sur_un_autre_horizon_nest_pas_recycle():
    """L'horizon doit être celui que NOTRE latence atteint : pas de substitution silencieuse."""
    episodes = _eps(30, 50.0, horizon=5000)
    s = _score(episodes)             # on demande 1000 ms
    assert s["statut"] == "NON_MESURE" and s["n_sans_markout"] == 30


# ═══════════════ un seul gros coup ═══════════════
def test_un_edge_venant_dun_seul_coup_nest_pas_eligible_core():
    episodes = _eps(29, 0.5) + _eps(1, 500.0, t0=T0 + 500_000)
    s = _score(episodes, cout=0.0)
    assert s["score_copyable_bps"] > 0
    assert s["un_seul_gros_coup"] is True and s["eligible_core"] is False


# ═══════════════ classement et slots ═══════════════
def test_seuls_les_mesures_et_eligibles_sont_classes():
    scores = {"a": _score(_eps(30, 20.0)), "b": _score(_eps(30, 5.0)), "c": _score(_eps(3, 99.0))}
    assert WS.classer(scores) == [("a", 11.0)]


def test_la_shortlist_respecte_la_limite_hyperliquid():
    r = WS.shortlist({}, n_core=9, n_challengers=3)
    assert r["erreur"] == "SLOTS_AU_DELA_DE_LA_LIMITE_HL" and r["core"] == []


def test_les_slots_se_composent_de_core_mesures_et_de_challengers_explores():
    scores = {"w%d" % i: _score(_eps(30, 20.0 + i)) for i in range(10)}
    scores.update({"neuf1": _score(_eps(2, 0.0)), "neuf2": _score(_eps(2, 0.0))})
    r = WS.shortlist(scores)
    assert len(r["core"]) == WS.N_CORE and len(r["challengers"]) == WS.N_CHALLENGERS
    assert r["slots_utilises"] == 10 and r["slots_utilises"] <= WS.LIMITE_SLOTS_HL
    assert set(r["challengers"]) <= {"neuf1", "neuf2"}          # l'exploration va aux non mesures
    assert "w9" in r["core"]                                     # le meilleur mesure est retenu


def test_un_wallet_non_mesure_ne_prend_jamais_une_place_core():
    scores = {"mesure": _score(_eps(30, 20.0)), "inconnu": _score(_eps(1, 999.0))}
    r = WS.shortlist(scores)
    assert "inconnu" not in r["core"] and "inconnu" in r["challengers"]


def test_lhysteresis_empeche_de_permuter_pour_du_bruit():
    """Un prétendant à +0,5 bps ne déloge pas un titulaire : on permuterait sans rien mesurer."""
    scores = {"w%d" % i: _score(_eps(30, 20.0)) for i in range(8)}
    scores["pretendant"] = _score(_eps(30, 20.5))               # +0,5 bps seulement
    actuels = ["w%d" % i for i in range(8)]
    r = WS.shortlist(scores, slots_actuels=actuels, marge_hysteresis_bps=2.0)
    assert r["remplacements"] == [] and "pretendant" not in r["core"]


def test_un_pretendant_nettement_meilleur_deloge_le_plus_faible():
    scores = {"w%d" % i: _score(_eps(30, 20.0)) for i in range(8)}
    scores["fort"] = _score(_eps(30, 40.0))                     # +20 bps
    actuels = ["w%d" % i for i in range(8)]
    r = WS.shortlist(scores, slots_actuels=actuels, marge_hysteresis_bps=2.0)
    assert "fort" in r["core"] and len(r["remplacements"]) == 1
    assert r["remplacements"][0]["entrant"] == "fort"


def test_les_candidats_dexploration_explicites_passent_devant():
    scores = {"mesure": _score(_eps(30, 20.0)), "inconnu": _score(_eps(1, 0.0))}
    r = WS.shortlist(scores, candidats_exploration=["nouveau"], n_core=1, n_challengers=1)
    assert r["challengers"] == ["nouveau"]


def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "following" / "wallet_scoring_shortlist.py").read_text(
        encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans wallet_scoring_shortlist: %s" % interdit
