"""[COPY-VAULT #79] drift ledger : quantité et raison de chaque écart cible/réel conservées."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.drift_ledger import DriftLedger, ROUNDING, LIQUIDITY   # noqa: E402


def test_ventilation_par_raison():
    led = DriftLedger()
    led.enregistrer("BTC", 0.01, ROUNDING)
    led.enregistrer("BTC", -0.05, LIQUIDITY)
    r = led.resume()
    assert r["n_entrees"] == 2 and r["drift_total"] == 0.06
    assert r["par_raison"][ROUNDING] == 0.01 and r["par_raison"][LIQUIDITY] == 0.05


def test_raison_hors_taxonomie_en_autre():
    led = DriftLedger()
    led.enregistrer("ETH", 0.02, "BIZARRE")
    assert led.resume()["par_raison"]["AUTRE"] == 0.02   # jamais silencieusement ignorée


def test_quantite_invalide_refusee():
    led = DriftLedger()
    assert led.enregistrer("ETH", None, ROUNDING)["ok"] is False
