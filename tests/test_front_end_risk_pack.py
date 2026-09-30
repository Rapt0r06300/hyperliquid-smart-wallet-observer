"""[lot2 #99] front-end risk pack : débit/actifs/volume/ratio cancel plafonnés par module."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.risk_gates.front_end_risk_pack import ControleFrontEnd   # noqa: E402


def test_dans_les_limites():
    c = ControleFrontEnd(max_ordres_par_s=10.0, max_ordres_actifs=50, volume_max_par_ordre=1e6)
    r = c.valider_ordre(debit_ordres_par_s=5.0, ordres_actifs=10, volume_ordre=1000.0)
    assert r["ok"] is True


def test_debit_depasse():
    c = ControleFrontEnd(max_ordres_par_s=10.0)
    r = c.valider_ordre(debit_ordres_par_s=20.0, ordres_actifs=1, volume_ordre=1.0)
    assert r["ok"] is False and "DEBIT_ORDRES" in r["violations"]


def test_ratio_cancel_depasse():
    c = ControleFrontEnd(ratio_cancel_max=0.9)
    r = c.valider_ordre(debit_ordres_par_s=1.0, ordres_actifs=1, volume_ordre=1.0, n_envois=20, n_cancels=19)
    assert "RATIO_CANCEL" in r["violations"]
