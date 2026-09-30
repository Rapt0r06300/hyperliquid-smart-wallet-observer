"""[ARB #25] churn accounting : le rendement détruit par cancels/reprices doit apparaître au bilan."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.churn_accounting import ChurnLedger   # noqa: E402


def test_cancel_detruit_edge_et_frais():
    led = ChurnLedger()
    led.enregistrer_cancel(edge_abandonne_bps=20.0, notional_usd=1000.0, frais_cancel_usd=0.5)
    r = led.resume()
    # 20 bps de 1000$ = 2$ + 0.5$ frais = 2.5$
    assert r["rendement_detruit_usd"] == 2.5 and r["n_cancels"] == 1


def test_reprice_compte_dans_le_churn():
    led = ChurnLedger()
    led.enregistrer_reprice(cout_bps=5.0, notional_usd=2000.0)
    r = led.resume()
    assert r["rendement_detruit_usd"] == 1.0 and r["n_reprices"] == 1


def test_total_evenements():
    led = ChurnLedger()
    led.enregistrer_cancel(edge_abandonne_bps=10.0, notional_usd=1000.0)
    led.enregistrer_reprice(cout_bps=5.0, notional_usd=1000.0)
    assert led.resume()["n_evenements"] == 2
