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
