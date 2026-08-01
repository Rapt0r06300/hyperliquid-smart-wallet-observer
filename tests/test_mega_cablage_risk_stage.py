"""[CABLAGE étage E] risk_stage : garde-fous pretrade (notional cap + drawdown + verrou module)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.risk_stage import filtrer_risque   # noqa: E402
from hl_observer.risk_gates.account_equity_max_drawdown import MaxDrawdownCooldown   # noqa: E402
from hl_observer.risk_gates.low_profit_module_lock import VerrouFaibleProfit   # noqa: E402

CAND = {"valide": True, "coin": "BTC", "cote": "BUY", "quantite": 0.008,
        "prix": 60000.0, "type_exec": "TAKER", "notional": 500.0}


def test_dans_plafond_autorise():
    assert filtrer_risque(CAND, notional_max=500.0, coin="BTC", now_ms=0)["autorise"] is True


def test_notional_depasse_refuse():
    r = filtrer_risque(CAND, notional_max=400.0, coin="BTC", now_ms=0)
    assert r["autorise"] is False and r["raison"] == "NOTIONAL_DEPASSE_LIMITE"


def test_drawdown_halte_et_verrou_module():
    dd = MaxDrawdownCooldown(seuil_drawdown_pct=10.0)
    dd.evaluer(1000.0, now_ms=0)                       # pic 1000
    r = filtrer_risque(CAND, notional_max=500.0, coin="BTC", now_ms=1000,
                       drawdown_gate=dd, equity=800.0)  # -20% -> HALTED
    assert r["autorise"] is False and r["raison"] == "MAX_DRAWDOWN_HALTED"
    v = VerrouFaibleProfit(min_episodes=1, seuil_net=0.0, cooldown_s=1000.0)
    v.enregistrer_episode("BTC", -5.0, t=0)            # verrouille jusqu'à 1000
    r2 = filtrer_risque(CAND, notional_max=500.0, coin="BTC", now_ms=10, verrou=v)
    assert r2["autorise"] is False and r2["raison"] == "MODULE_VERROUILLE"
