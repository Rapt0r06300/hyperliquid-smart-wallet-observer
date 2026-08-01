"""[pépite 292] late-start protection : début d'observation mi-epoch → ne pas traiter le REDUCE comme position complète."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.late_start_protection import ProtectionDepartTardif   # noqa: E402


def test_reduce_sans_open_est_depart_tardif():
    p = ProtectionDepartTardif()
    r = p.observer("REDUCE")
    assert r["depart_tardif"] is True and r["repliquer_comme_complet"] is False
    assert r["position_base"] == "INCONNUE"


def test_open_puis_reduce_ok():
    p = ProtectionDepartTardif()
    p.observer("OPEN")
    r = p.observer("REDUCE")
    assert r["depart_tardif"] is False and r["repliquer_comme_complet"] is True


def test_reset_epoch():
    p = ProtectionDepartTardif()
    p.observer("OPEN")
    p.reset_epoch()
    assert p.observer("CLOSE")["depart_tardif"] is True
