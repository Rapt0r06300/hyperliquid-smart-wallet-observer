"""[pépite 261] channel coverage matrix : % temps couvert par coin×channel, avec les trous précis."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.dataset.channel_coverage_matrix import construire   # noqa: E402


def test_couverture_et_trous():
    couv = {"BTC": {"L2": [(0.0, 40.0), (60.0, 100.0)]}}   # 80/100 couvert, trou 40-60
    r = construire(couv, 0.0, 100.0)
    cell = r["matrice"]["BTC"]["L2"]
    assert cell["pct"] == 0.8 and (40.0, 60.0) in cell["trous"]


def test_intervalles_chevauchants_fusionnes():
    couv = {"ETH": {"BBO": [(0.0, 50.0), (30.0, 100.0)]}}  # fusion -> 0-100 = 100%
    assert construire(couv, 0.0, 100.0)["matrice"]["ETH"]["BBO"]["pct"] == 1.0


def test_fenetre_invalide():
    assert construire({"BTC": {"L2": []}}, 100.0, 0.0)["matrice"] == {}
