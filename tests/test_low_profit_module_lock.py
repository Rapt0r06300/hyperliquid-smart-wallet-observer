"""[pépite 300] low-profit module lock : assez d'épisodes mais sous le seuil net → cooldown auto (hors stoploss/MaxDD)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.risk_gates.low_profit_module_lock import VerrouFaibleProfit   # noqa: E402


def test_verrou_sur_faible_profit():
    v = VerrouFaibleProfit(min_episodes=3, seuil_net=0.0, cooldown_s=100.0)
    v.enregistrer_episode("BTC", -1.0, t=1000.0)
    v.enregistrer_episode("BTC", -1.0, t=1000.0)
    r = v.enregistrer_episode("BTC", -1.0, t=1000.0)     # 3 épisodes, net -3 < 0
    assert r["verrou_declenche"] is True and r["jusqu_a"] == 1100.0
    assert v.est_verrouille("BTC", 1050.0)["verrouille"] is True
    assert v.est_verrouille("BTC", 1200.0)["verrouille"] is False   # cooldown expiré


def test_module_rentable_pas_verrouille():
    v = VerrouFaibleProfit(min_episodes=3, seuil_net=0.0)
    for _ in range(3):
        v.enregistrer_episode("ETH", 5.0, t=1000.0)      # net +15
    assert v.est_verrouille("ETH", 1000.0)["verrouille"] is False


def test_pas_assez_d_episodes():
    v = VerrouFaibleProfit(min_episodes=3, seuil_net=0.0)
    v.enregistrer_episode("SOL", -5.0, t=1000.0)
    r = v.enregistrer_episode("SOL", -5.0, t=1000.0)     # 2 épisodes < 3
    assert r["verrou_declenche"] is False
