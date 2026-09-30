"""[pépite 241] route switching cost : le coût de bascule fait partie de la décision de routage."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.routing.route_switching_cost import vaut_le_switch   # noqa: E402


def test_switch_rentable():
    r = vaut_le_switch(gain_route_b_bps=10.0, cout_switch_bps=3.0)
    assert r["switcher"] is True and r["gain_net_bps"] == 7.0


def test_switch_non_rentable():
    r = vaut_le_switch(gain_route_b_bps=2.0, cout_switch_bps=5.0)   # gain < cout de bascule
    assert r["switcher"] is False and r["raison"] == "SWITCH_NON_RENTABLE"


def test_cout_non_mesurable():
    assert vaut_le_switch(gain_route_b_bps=None, cout_switch_bps=3.0)["switcher"] is False
