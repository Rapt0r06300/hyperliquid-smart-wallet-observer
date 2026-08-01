"""[COPY-VAULT #52] exposure-ratio replication : cible = (notional_leader/equity_leader) x notre_equity."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.exposure_ratio_replication import exposition_cible   # noqa: E402


def test_part_dexposition():
    r = exposition_cible(notional_leader=50000.0, equity_leader=100000.0, notre_equity=5000.0)
    assert r["part_equity_leader"] == 0.5 and r["notional_cible"] == 2500.0   # 50% de notre equity


def test_equity_leader_nulle_refuse():
    r = exposition_cible(notional_leader=50000.0, equity_leader=0.0, notre_equity=5000.0)
    assert r["notional_cible"] == "UNMEASURABLE" and r["refuse"] is True


def test_entree_invalide():
    assert exposition_cible(notional_leader=None, equity_leader=100000.0, notre_equity=5000.0)["refuse"] is True
