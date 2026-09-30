"""[ALL #97] volume-share slippage stress : impact ~ (taille/volume)^2, détecte les tailles absurdes."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.volume_share_slippage_stress import impact_bps, taille_absurde   # noqa: E402


def test_impact_quadratique():
    # part 0.1 -> 0.01 * 1e4 = 100 bps ; part 0.2 -> 0.04*1e4 = 400 bps (x4 pour x2 de taille)
    assert impact_bps(10.0, 100.0, coef=1.0) == 100.0
    assert impact_bps(20.0, 100.0, coef=1.0) == 400.0


def test_taille_absurde_detectee():
    r = taille_absurde(50.0, 100.0, part_max=0.1)        # 50% du volume
    assert r["absurde"] is True and r["raison"] == "TAILLE_ABSURDE"
    assert taille_absurde(5.0, 100.0, part_max=0.1)["absurde"] is False


def test_volume_invalide_fail_closed():
    assert impact_bps(10.0, 0.0) == "UNMEASURABLE"
    assert taille_absurde(10.0, 0.0)["absurde"] is True
