"""[pépite 293] epoch-local checkpoint : à partir de quel fill d'un cycle la réplication paper a commencé."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.epoch_local_checkpoint import CheckpointEpoch   # noqa: E402


def test_premier_debut_fait_foi():
    c = CheckpointEpoch()
    assert c.marquer_debut(1, "fill_A")["nouveau"] is True
    r = c.marquer_debut(1, "fill_B")               # ne réécrit pas
    assert r["nouveau"] is False and r["fill_debut"] == "fill_A"


def test_couverture_complete():
    c = CheckpointEpoch()
    c.marquer_debut(1, "fill_A")
    assert c.couvre_tout_lepoch(1, "fill_A")["couverture_complete"] is True


def test_couverture_partielle():
    c = CheckpointEpoch()
    c.marquer_debut(1, "fill_C")                    # on a commencé au 3e fill
    assert c.couvre_tout_lepoch(1, "fill_A")["couverture_complete"] is False
