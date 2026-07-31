"""ALPHA P2 — Wallet×Binance anticipation : sens move_before/after, follower=KILL, anticipateur, verdicts."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import wallet_binance_anticipation as A  # noqa: E402

JOUR = 86_400_000


def _serie(points):
    points = sorted(points)
    return ([p[0] for p in points], [p[1] for p in points])


def test_move_after_positif_si_binance_suit_le_fill():
    # Binance monte APRES T -> anticipateur (fill LONG)
    serie = _serie([(0, 100.0), (1000, 100.0), (6000, 100.5)])
    r = A.anticipation_fill(serie, {"side": "LONG", "ts_ms": 1000}, horizons_ms=(5000,))
    assert r[5000]["after"] > 0


def test_move_before_positif_si_binance_a_deja_bouge():
    # Binance a monté AVANT T -> follower (fill LONG)
    serie = _serie([(0, 100.0), (5000, 100.5), (6000, 100.5)])
    r = A.anticipation_fill(serie, {"side": "LONG", "ts_ms": 6000}, horizons_ms=(5000,))
    assert r[5000]["before"] > 0


def test_horizon_sous_cadence_non_mesurable():
    serie = _serie([(0, 100.0), (10000, 101.0)])
    r = A.anticipation_fill(serie, {"side": "LONG", "ts_ms": 0}, horizons_ms=(50,), tol_ms=100)
    assert r[50]["after"] is None                      # aucun point Binance à ±50ms -> UNMEASURABLE


def test_fix16_point_stale_loin_de_horizon_rejete():
    # FIX-16 : à T+h=15000, le SEUL point <= 15000 est stale (11000, 4 s trop vieux). L'ancien code
    # ("dernier <= T+h") l'aurait pris et appelé "horizon 5000". Le nouveau exige un point PROCHE de 15000.
    serie = _serie([(10000, 100.0), (11000, 100.5)])   # rien près de 15000
    r = A.anticipation_fill(serie, {"side": "LONG", "ts_ms": 10000}, horizons_ms=(5000,), tol_ms=1000)
    assert r[5000]["after"] is None                    # pas de mid à ±(<=h/2) de 15000 -> UNMEASURABLE, jamais le stale


def test_fix16_prend_le_point_le_plus_proche_pas_le_dernier_avant():
    # Deux points encadrent T+h=15000 : un stale AVANT (12000, d=3000) et un frais APRES (15100, d=100).
    # "dernier <= T+h" prendrait le stale 12000 ; le fix prend 15100 (le plus proche).
    serie = _serie([(10000, 100.0), (12000, 100.3), (15100, 100.9)])
    r = A.anticipation_fill(serie, {"side": "LONG", "ts_ms": 10000}, horizons_ms=(5000,), tol_ms=1000)
    # doit refléter 15100 (100.9 -> +90 bps), PAS le stale 12000 (100.3 -> +30 bps)
    assert r[5000]["after"] == 90.0


def test_fix17_close_short_est_un_achat_close_long_une_vente():
    # FIX-17 : le sens NE vient PAS du seul position_side. Fermer un SHORT = ACHAT (+1) ; fermer un LONG = VENTE (-1).
    assert A.direction_trade({"dir": "Close Short"}) == 1.0
    assert A.direction_trade({"dir": "Close Long"}) == -1.0
    assert A.direction_trade({"action": "CLOSE", "position_side": "short"}) == 1.0
    assert A.direction_trade({"action": "REDUCE", "position_side": "long"}) == -1.0


def test_fix17_open_et_side_explicite_et_flip():
    assert A.direction_trade({"dir": "Open Long"}) == 1.0
    assert A.direction_trade({"dir": "Open Short"}) == -1.0
    assert A.direction_trade({"side": "B"}) == 1.0 and A.direction_trade({"side": "A"}) == -1.0
    assert A.direction_trade({"dir": "Long > Short"}) == -1.0      # flip long->short = vente nette
    assert A.direction_trade({"dir": "Short > Long"}) == 1.0       # flip short->long = achat net
    # rétro-compat : side long/short seul = OPEN implicite
    assert A.direction_trade({"side": "LONG"}) == 1.0 and A.direction_trade({"side": "SHORT"}) == -1.0


def test_fix17_indeterminable_rend_unmeasurable():
    assert A.direction_trade({"coin": "BTC", "ts_ms": 1}) is None
    serie = _serie([(0, 100.0), (1000, 100.0), (6000, 100.5)])
    r = A.anticipation_fill(serie, {"ts_ms": 1000}, horizons_ms=(5000,))   # pas de direction -> UNMEASURABLE
    assert r[5000]["after"] is None and r[5000]["before"] is None


def test_fix17_close_short_inverse_le_signe_de_move_after():
    # Binance MONTE de +50 bps apres le fill. Un CLOSE SHORT est un ACHAT -> move_after favorable = +50.
    # L'ancien code (side=SHORT -> -1) l'aurait compte -50 : un vrai anticipateur maquille en follower.
    serie = _serie([(0, 100.0), (1000, 100.0), (6000, 100.5)])
    r = A.anticipation_fill(serie, {"dir": "Close Short", "ts_ms": 1000}, horizons_ms=(5000,))
    assert r[5000]["after"] == 50.0                                # +1 * (100.5/100 - 1) * 1e4


def test_fix18_charger_fills_deduplique_par_evenement(tmp_path):
    import json as _j
    rows = [
        {"adresse": "0xA", "coin": "BTC", "side": "LONG", "ts_ms": 1, "tid": "t1"},
        {"adresse": "0xA", "coin": "BTC", "side": "LONG", "ts_ms": 1, "tid": "t1"},        # meme tid -> doublon
        {"adresse": "0xA", "coin": "BTC", "side": "LONG", "ts_ms": 2, "tid": "t2"},        # distinct
        {"adresse": "0xB", "coin": "ETH", "side": "SHORT", "ts_ms": 5, "px": 100, "sz": 3},
        {"adresse": "0xB", "coin": "ETH", "side": "SHORT", "ts_ms": 5, "px": 100, "sz": 3},  # raw-doublon (sans id)
    ]
    p = tmp_path / "fills.jsonl"
    p.write_text("\n".join(_j.dumps(r) for r in rows), encoding="utf-8")
    fills = A.charger_fills(str(p))
    assert len(fills) == 3                                  # 2 doublons retires (tid t1, et le raw ETH)
    assert A.cle_dedup_fill({"tid": "x", "adresse": "0xA"}) == "tid:x"   # id explicite prime sur l'empreinte


def _bin_series_anticipee(coin_base=100.0, n_days=4):
    # série Binance dense ; à chaque "fill time" Binance monte de +20 bps sur les 5 s suivantes
    pts = []
    fills = []
    for d in range(n_days):
        base_t = d * JOUR
        for k in range(3):
            T = base_t + k * 60_000 + 30_000
            m = coin_base
            pts += [(T - 6000, m), (T - 1000, m), (T, m), (T + 5000, m * 1.002), (T + 6000, m * 1.002)]
            fills.append({"adresse": "0xANTI", "coin": "BTC", "side": "LONG", "ts_ms": T})
    return _serie(pts), fills


def test_experience_anticipateur_ou_more_data():
    serie, fills = _bin_series_anticipee()
    r = A.experience_anticipation(fills, {"BTC": serie}, horizon_ms=5000, cout_bps=0.0, min_fills_wallet=8)
    assert r["n_wallets_mesures"] == 1
    v = r["classement"][0]
    assert v["move_after_bps"] > 0                       # Binance suit le fill
    assert v["verdict"] in ("ANTICIPATEUR_A_FORWARD", "MORE_DATA")


def _fills_par_jour(after_by_day, wallet="0xW"):
    # un fill LONG par jour ; Binance bouge de `frac` sur [T, T+5s]. after_bps = frac*1e4.
    pts, fills = [], []
    for d, frac in enumerate(after_by_day):
        T = d * JOUR + 30_000
        pts += [(T, 100.0), (T + 5000, 100.0 * (1.0 + frac))]
        fills.append({"adresse": wallet, "coin": "BTC", "side": "LONG", "ts_ms": T})
    return _serie(pts), fills


def test_fix20_edge_qui_ne_survit_pas_en_oos_est_KILL():
    # +60 bps en DÉCOUVERTE (14 jours), puis -10 bps en OOS (10 jours) : l'edge repéré NE survit PAS -> KILL.
    serie, fills = _fills_par_jour([0.006] * 14 + [-0.001] * 10)
    r = A.experience_anticipation(fills, {"BTC": serie}, horizon_ms=5000, cout_bps=9.0, min_fills_wallet=8)
    v = r["classement"][0]
    assert v["verdict"] == "KILL"                           # jamais promu sur la seule fenêtre de découverte
    assert v["lcb_decouverte_bps"] > 0 and v["lcb_net_bps"] <= 0   # bon en découverte, mort en OOS


def test_fix20_edge_confirme_en_oos_est_anticipateur():
    # +55/+65 bps sur découverte ET OOS : l'edge survit hors-échantillon -> ANTICIPATEUR_A_FORWARD.
    serie, fills = _fills_par_jour([0.0055, 0.0065] * 12)   # 24 jours, alternance légère
    r = A.experience_anticipation(fills, {"BTC": serie}, horizon_ms=5000, cout_bps=9.0, min_fills_wallet=8)
    v = r["classement"][0]
    assert v["verdict"] == "ANTICIPATEUR_A_FORWARD"
    assert v["lcb_decouverte_bps"] > 0 and v["lcb_net_bps"] > 0 and v["n_independent"] >= 8


def test_experience_follower_est_KILL():
    # Binance monte AVANT chaque fill -> follower
    pts, fills = [], []
    for d in range(4):
        for k in range(3):
            T = d * JOUR + k * 60_000 + 30_000
            # la hausse Binance est DANS [T-5000, T] : mb@T-5000=100.0, m0@T=100.3 -> before=+30bps
            pts += [(T - 6000, 100.0), (T - 2000, 100.3), (T, 100.3), (T + 5000, 100.3)]
            fills.append({"adresse": "0xFOLLOW", "coin": "BTC", "side": "LONG", "ts_ms": T})
    r = A.experience_anticipation(fills, {"BTC": _serie(pts)}, horizon_ms=5000, cout_bps=9.0, min_fills_wallet=8)
    assert r["classement"][0]["verdict"] in ("KILL_FOLLOWER", "MORE_DATA")
    assert r["classement"][0]["move_before_bps"] > 0
