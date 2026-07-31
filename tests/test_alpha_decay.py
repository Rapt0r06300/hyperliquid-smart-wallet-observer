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
