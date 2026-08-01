"""[LAB α] lab_metriques : métriques (PF, drawdown, ES, LCB, HHI, turnover) + gate de promotion dure."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops.lab_metriques import (   # noqa: E402
    profit_factor, drawdown, lcb_moyenne, hhi, turnover, metriques_candidat, verdict_promotion)


def test_metriques_de_base():
    assert profit_factor([2.0, 1.0, -1.0]) == 3.0
    assert drawdown([100.0, 110.0, 90.0, 105.0]) == 20.0
    assert hhi({"BTC": 8.0, "ETH": 2.0}) == round(0.8 ** 2 + 0.2 ** 2, 6)
    assert turnover(500.0, 1000.0) == 0.5


def test_promotion_promu():
    seg = {"IS": {"net": 10.0, "roi": 0.01}, "OOS": {"net": 4.0}, "FORWARD": {"net": 3.0},
           "ADVERSE_P95": {"net": 1.0}, "ADVERSE_P99": {"net": 0.5}}
    m = metriques_candidat(segments=seg, nets_episodes=[1.0] * 40, courbe_equity=[1000, 1010],
                           notional_traite=500.0, equity_finale=1010.0, fees=0.5,
                           contributions_coin={"BTC": 10.0}, capacite=250.0, reconcilie=True)
    assert m["lcb"] > 0 and verdict_promotion(m) == "PROMU"


def test_promotion_kill_more_data_unmeasurable():
    base = {"reconcilie": True, "capacite": 100.0, "n_episodes": 40, "net_pnl": 10.0,
            "oos_net": -1.0, "forward_net": 3.0, "lcb": 1.0, "adverse_p95_net": 1.0}
    assert verdict_promotion(base) == "KILL"                          # OOS négatif
    assert verdict_promotion({**base, "n_episodes": 3}) == "MORE_DATA"
    assert verdict_promotion({**base, "capacite": "UNMEASURABLE"}) == "UNMEASURABLE"
    assert verdict_promotion({**base, "reconcilie": False}) == "KILL"
