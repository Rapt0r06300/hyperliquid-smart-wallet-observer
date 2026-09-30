"""[COPY-VAULT lot2 #42] equity et positions en parallèle : latence = max, pas somme."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.parallel_state_read import latence_lecture   # noqa: E402


def test_parallele_est_le_max():
    r = latence_lecture(latence_equity_ms=30.0, latence_positions_ms=50.0, parallele=True)
    assert r["latence_ms"] == 50.0 and r["gain_ms"] == 30.0


def test_sequentiel_est_la_somme():
    r = latence_lecture(latence_equity_ms=30.0, latence_positions_ms=50.0, parallele=False)
    assert r["latence_ms"] == 80.0


def test_latence_invalide():
    assert latence_lecture(latence_equity_ms=None, latence_positions_ms=50.0)["latence_ms"] == "UNMEASURABLE"
