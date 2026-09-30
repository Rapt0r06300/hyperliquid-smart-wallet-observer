"""ALPHA P32 — courbes de decay : pic, half_life, break_even_latency, NO_TRADE apres max age."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import alpha_decay as D  # noqa: E402


def test_courbe_decay_pic_half_life_breakeven():
    # net decroit avec l'age : pic 8 @100ms, moitie (4) vers 500ms, croise 0 vers ~1000ms
    courbe = D.courbe_decay({100: 8.0, 250: 6.0, 500: 4.0, 1000: 0.0, 2000: -4.0})
    assert courbe["pic_bps"] == 8.0 and courbe["age_pic_ms"] == 100
    assert courbe["half_life_ms"] == 500                     # net = 4 (moitie du pic) a 500ms
    assert courbe["break_even_latency_ms"] == 1000           # net = 0 a 1000ms


def test_no_trade_apres_max_age():
    courbe = D.courbe_decay({100: 8.0, 1000: 0.0, 2000: -4.0})
    assert D.no_trade(1500, courbe) is True                   # au-dela du break-even -> NO_TRADE
    assert D.no_trade(500, courbe) is False


def test_courbe_insuffisante():
    assert D.courbe_decay({100: 8.0})["pic_bps"] == D.UNMEASURABLE


def test_fix39_mesure_decay_reel_front_loaded():
    # edge FRONT-LOADED : le prix saute a T+500 puis reste plat. Entrer tot capture +50 bps ; entrer trop tard = 0.
    T = 30_000
    pts = [(T, 100.0)] + [(T + t, 100.5) for t in (500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500)]
    serie = ([p[0] for p in pts], [p[1] for p in pts])
    sig = [{"coin": "BTC", "ts_ms": T, "sens": 1.0}]
    r = D.mesurer_decay_par_age(sig, {"BTC": serie}, ages_ms=(0, 500, 1000, 2000),
                                holding_ms=2000, cout_bps=9.0)
    assert r["net_par_age_ms"][0] == 41.0                      # age 0 : (100.5/100-1)*1e4 - 9 = 41
    assert r["net_par_age_ms"][500] == -9.0                    # age 500 : entre a 100.5, sort a 100.5 -> -9
    assert r["pic_bps"] == 41.0 and r["age_pic_ms"] == 0
    # break-even entre 0 et 500 : 500 * 41 / (41+9) = 410 ms
    assert r["break_even_latency_ms"] == 410.0
    assert D.no_trade(500, r) is True and D.no_trade(300, r) is False
