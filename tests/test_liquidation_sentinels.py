"""LIQUIDATION_SENTINELS_V2 — cœur causal prouvé sans réseau (Flo 25/07).

Prouve la ligne dure : (1) entrée = 1re cotation STRICTEMENT APRÈS recv+latence — JAMAIS antérieure, JAMAIS
« la plus proche ±2 s » ; (2) REST_BACKFILL = descriptif/OOS, jamais causal ; (3) exécution BBO refusée si
touch < 2× notional ; (4) décision armable seulement à 10 épisodes live, 5/moitié, positif des 2 côtés + LOO ;
(5) sélection des sentinelles par épisodes-liquidateur.
"""
from __future__ import annotations

from hl_observer.experimental import liquidation_sentinels as LS


# ── 1. Sentinelles ─────────────────────────────────────────────────────────
def test_selection_sentinelles_par_episodes_liquidateur():
    recs = (
        [{"coin": "ETH", "hash": "h%d" % i, "vault": "0xAAA", "liquidatedUser": "0xVIC"} for i in range(5)]
        + [{"coin": "SOL", "hash": "g%d" % i, "vault": "0xBBB", "liquidatedUser": "0xVIC"} for i in range(2)]
        + [{"coin": "BTC", "hash": "k0", "vault": "0xCCC", "liquidatedUser": "0xCCC"}]   # AUTO-liquidé -> ignoré
    )
    r = LS.selectionner_sentinelles(recs, k=2)
    assert r["sentinelles"] == ["0xAAA", "0xBBB"]        # classés par nb d'épisodes liquidateur
    assert r["par_vault"]["0xAAA"] == 5 and r["par_vault"]["0xBBB"] == 2
    assert "0xCCC" not in r["par_vault"]                 # auto-liquidation n'est pas un rôle liquidateur


# ── 2. Entrée causale : jamais de look-ahead ───────────────────────────────
def _serie(points):
    points = sorted(points, key=lambda p: p[0])
    return [p[0] for p in points], [(p[1], p[2], p[3], p[4]) for p in points]


def test_entree_est_la_PREMIERE_apres_recv_plus_latence():
    # seuil = recv 1000 + latence 400 = 1400. cotations à 900 (avant, exclue), 1400 (= seuil, exclue car
    # STRICTEMENT après), 1500 (1re valide), 1700. On prend 1500, pas la 'plus proche' d'avant.
    serie = _serie([(900, 10, 11, 1e6, 1e6), (1400, 15, 16, 1e6, 1e6),
                    (1500, 20, 21, 1e6, 1e6), (1700, 40, 41, 1e6, 1e6)])
    e = LS.entree_causale(1000.0, serie, latence_ms=400.0)
    assert e is not None and e[0] == 1500, "1re cotation STRICTEMENT après 1400 (pas 1400=seuil, pas 900)"


def test_jamais_de_cotation_anterieure():
    # UNIQUEMENT des cotations AVANT recv+latence (seuil 1400) -> aucune entrée causale (pas la 'plus proche' d'avant)
    serie = _serie([(100, 10, 11, 1e6, 1e6), (900, 12, 13, 1e6, 1e6), (1399, 14, 15, 1e6, 1e6)])
    assert LS.entree_causale(1000.0, serie, latence_ms=400.0) is None


def test_pas_la_plus_proche_si_hors_fenetre():
    # cotation existante à +5s après le seuil : « la plus proche » la prendrait ; la règle causale la REFUSE
    serie = _serie([(1400 + 5000, 10, 11, 1e6, 1e6)])
    assert LS.entree_causale(1000.0, serie, latence_ms=400.0, fenetre_max_ms=3000.0) is None


# ── 3. Exécution : BBO refusée si touch < 2× notional ──────────────────────
def test_execution_refuse_si_touch_insuffisant():
    e = (1600, 100.0, 100.1, 5.0, 5.0)          # touch 5 $ à l'ask
    s = (1660, 100.2, 100.3, 5.0, 5.0)
    r = LS.execution_bps(e, s, sens=+1, notional_usd=8.0)   # requis 16 $ > 5 $
    assert r["statut"] == "NON_MESURABLE" and r["motif"] == "TOUCH_INSUFFISANT"


def test_execution_ok_et_signe_long_short():
    e = (1600, 100.0, 100.1, 1e5, 1e5)
    s = (1660, 101.0, 101.1, 1e5, 1e5)          # le prix MONTE
    long = LS.execution_bps(e, s, sens=+1, notional_usd=8.0, fee_ar_bps=0.0, slippage_bps=0.0)
    short = LS.execution_bps(e, s, sens=-1, notional_usd=8.0, fee_ar_bps=0.0, slippage_bps=0.0)
    assert long["statut"] == "OK" and long["brut_bps"] > 0     # fade long gagne quand ça monte
    assert short["brut_bps"] < 0                                # fade short perd quand ça monte


# ── 4. Causalité deny-by-default : SEUL LIVE_WS + recv_wall_ms est causal ──
def test_rest_backfill_jamais_causal():
    ev = {"coin": "ETH", "recv_wall_ms": 1000.0, "sens": +1, "source": "REST_BACKFILL"}
    serie = _serie([(1600, 100, 100.1, 1e6, 1e6)])
    assert LS.mesurer_episode(ev, serie)["statut"] == "OOS_DESCRIPTIF"


def test_legacy_userfills_sans_horloge_reception_jamais_causal():
    # les 142 backfillés portent source 'userFills.liquidation' SANS recv_wall_ms -> jamais causal
    ev = {"coin": "ETH", "hash": "h", "vault": "0x", "source": "userFills.liquidation"}
    assert LS.est_causal(ev) is False
    assert LS.mesurer_episode(ev, _serie([(1600, 100, 100.1, 1e6, 1e6)]))["statut"] == "OOS_DESCRIPTIF"


def test_live_ws_avec_horloge_est_causal():
    assert LS.est_causal({"source": "LIVE_WS", "recv_wall_ms": 1000.0}) is True


def test_live_sans_cotation_causale_non_mesurable():
    ev = {"coin": "ETH", "recv_wall_ms": 1000.0, "sens": +1, "source": "LIVE_WS"}
    assert LS.mesurer_episode(ev, _serie([]))["statut"] == "NON_MESURABLE"


# ── 5. Décision : garde-fou 10 / 5-par-moitié / LOO ────────────────────────
def _episode(ts, net):
    return {"statut": "OK", "recv_wall_ms": ts, "par_horizon": {"30": {"statut": "OK", "net_bps": net}}}


def test_decision_bloque_sous_10_episodes():
    eps = [_episode(i, 5.0) for i in range(6)]
    d = LS.decision(eps)
    assert d["armable"] is False and d["motif"] == "PAS_ASSEZ_D_EPISODES_LIVE_CAUSAUX" and d["n"] == 6


def test_decision_arme_si_robuste():
    eps = [_episode(i, 4.0) for i in range(12)]            # 12 épisodes, tous +4 bps, 6/6 par moitié
    d = LS.decision(eps)
    assert d["armable"] is True and d["median_moitie1"] > 0 and d["median_moitie2"] > 0
    assert d["median_sans_meilleur"] > 0 and d["motif"] == "ARME_MICRO_COHORTE"


def test_decision_refuse_si_un_seul_episode_porte_le_gain():
    # 11 épisodes négatifs + 1 énorme gagnant -> médiane globale peut sembler ok mais LOO l'exclut
    eps = [_episode(i, -1.0) for i in range(11)] + [_episode(11, 500.0)]
    d = LS.decision(eps)
    assert d["armable"] is False, "un seul épisode ne doit jamais suffire (leave-one-out)"
