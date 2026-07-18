"""P1 — attribution du PnL par clé."""
from __future__ import annotations

import pytest

from hl_observer.analysis.pnl_attribution import attribution, gagnants_perdants

LEDGER = [
    {"kind": "OPEN", "coin": "HYPE", "realized_net_pnl_usdc": None},
    {"kind": "CLOSE", "coin": "HYPE", "realized_net_pnl_usdc": 5.0},
    {"kind": "CLOSE", "coin": "HYPE", "realized_net_pnl_usdc": -2.0},
    {"kind": "CLOSE", "coin": "PURR", "realized_net_pnl_usdc": -3.0},
]


def test_attribution_par_coin():
    a = attribution(LEDGER, cle="coin")
    assert a["HYPE"] == pytest.approx(3.0) and a["PURR"] == pytest.approx(-3.0)


def test_gagnants_perdants():
    gp = gagnants_perdants(LEDGER, cle="coin")
    assert gp["gagnants"] == {"HYPE": 3.0} and gp["perdants"] == {"PURR": -3.0}
