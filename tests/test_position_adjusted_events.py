"""[pépite 219] PositionAdjusted events : commissions/corrections distinctes des trades."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.accounting.position_adjusted_events import LedgerPositions, COMMISSION_BASE   # noqa: E402


def test_ajustement_distinct_du_trade():
    led = LedgerPositions()
    led.trade(coin="BTC", delta_qty=1.0)
    led.ajuster(coin="BTC", delta_qty=-0.001, cause=COMMISSION_BASE)
    assert led.position("BTC") == 0.999
    assert led.part_ajustements("BTC") == -0.001         # visible séparément


def test_cause_inconnue_refusee():
    led = LedgerPositions()
    assert led.ajuster(coin="BTC", delta_qty=-0.001, cause="MYSTERE")["ok"] is False


def test_position_agrege_tout():
    led = LedgerPositions()
    led.trade(coin="ETH", delta_qty=2.0)
    assert led.position("ETH") == 2.0
