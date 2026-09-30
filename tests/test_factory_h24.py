"""CHANTIER #70 — Factory H24 : DISCOVERY → FREEZE → OOS → FORWARD. Seul survit ce dont LCB(net forward) > 0."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import factory_h24 as H24   # noqa: E402

# 4 cycles de captures. cfgGOOD reste net>0 en forward (confirmé) ; cfgSNOOP se dégrade (snooping, rejeté) ;
# cfgLATE n'est promu qu'au dernier cycle -> scellé mais sans forward (non confirmable).
_TRIALS = {
    0: [{"_famille": "cfgGOOD", "verdict": "CANDIDAT", "net_bps": 20.0, "config_frozen": "cA"},
        {"_famille": "cfgSNOOP", "verdict": "CANDIDAT", "net_bps": 15.0, "config_frozen": "cB"}],
    1: [{"_famille": "cfgGOOD", "net_bps": 18.0}, {"_famille": "cfgSNOOP", "net_bps": -5.0}],
    2: [{"_famille": "cfgGOOD", "net_bps": 22.0}, {"_famille": "cfgSNOOP", "net_bps": -8.0}],
    3: [{"_famille": "cfgGOOD", "net_bps": 19.0}, {"_famille": "cfgSNOOP", "net_bps": -3.0},
        {"_famille": "cfgLATE", "verdict": "CANDIDAT", "net_bps": 30.0, "config_frozen": "cC"}],
}


def _prod(cyc):
    return _TRIALS[cyc]


def test_chantier70_discipline_discovery_freeze_oos_forward():
    res = H24.lancer_h24([0, 1, 2, 3], _prod)
    assert res["n_scelles"] == 3 and res["n_confirmes"] == 1
    good = res["candidats"]["cfgGOOD"]
    assert good["confirme"] is True and good["n_forward"] == 3 and good["lcb_forward_bps"] > 0
    snoop = res["candidats"]["cfgSNOOP"]
    assert snoop["confirme"] is False and snoop["lcb_forward_bps"] <= 0     # bon en découverte, mort en forward
    assert res["candidats"]["cfgLATE"]["stade"] == "FREEZE_SANS_FORWARD"    # scellé tard, pas encore prouvé


def test_chantier70_pas_de_capture_rien_scelle():
    res = H24.lancer_h24([], _prod)
    assert res["n_scelles"] == 0 and res["n_confirmes"] == 0 and res["real_execution"] is False
