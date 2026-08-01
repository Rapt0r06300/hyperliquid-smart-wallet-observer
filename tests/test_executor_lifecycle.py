"""[ALL #89] explicit executor lifecycle : RUNNING/SHUTTING_DOWN/COMPLETED/FAILED/POSITION_HOLD contrôlés."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core import executor_lifecycle as EL   # noqa: E402


def test_chemin_normal():
    c = EL.CycleVieExecutor()
    assert c.etat == EL.RUNNING
    assert c.transition(EL.SHUTTING_DOWN)["ok"] is True
    assert c.transition(EL.COMPLETED)["ok"] is True and c.terminal() is True


def test_saut_interdit():
    c = EL.CycleVieExecutor()
    r = c.transition(EL.COMPLETED)                        # RUNNING -> COMPLETED direct interdit
    assert r["ok"] is False and c.etat == EL.RUNNING


def test_position_hold_terminal_explicite():
    c = EL.CycleVieExecutor()
    c.transition(EL.SHUTTING_DOWN)
    assert c.transition(EL.POSITION_HOLD)["ok"] is True   # résidu explicite, pas un oubli
