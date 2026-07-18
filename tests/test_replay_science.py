"""Science du replay — bootstrap IC (distinct de zéro), segmentation régime, attribution."""
from __future__ import annotations

from hl_observer.backtesting.replay_science import attribution, bootstrap_ic_pnl, segmenter_par_regime


def test_bootstrap_distingue_zero_ou_non():
    fort = bootstrap_ic_pnl([10.0] * 50)                 # tous +10 -> IC clairement > 0
    assert fort["distinct_de_zero"] is True and fort["ic_bas"] > 0
    bruite = bootstrap_ic_pnl([5.0, -5.0, 4.0, -6.0, 5.0, -4.0])   # autour de 0
    assert bruite["distinct_de_zero"] is False
    assert bootstrap_ic_pnl([1.0])["distinct_de_zero"] is False    # 1 point -> non concluant


def test_segmentation_regime():
    trades = [{"regime": "FUNDING_HAUT", "pnl": 3.0}, {"regime": "FUNDING_BAS", "pnl": -1.0},
              {"regime": "FUNDING_HAUT", "pnl": 2.0}]
    seg = segmenter_par_regime(trades)
    assert seg["FUNDING_HAUT"] == [3.0, 2.0] and seg["FUNDING_BAS"] == [-1.0]


def test_attribution_triee():
    trades = [{"coin": "HYPE", "pnl": 5.0}, {"coin": "PURR", "pnl": 2.0}, {"coin": "HYPE", "pnl": 1.0}]
    att = attribution(trades, "coin")
    assert att == {"HYPE": 6.0, "PURR": 2.0} and list(att)[0] == "HYPE"
