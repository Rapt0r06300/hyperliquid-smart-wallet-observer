"""[ALL lot2 #71] warm-up barrier global : aucune stratégie ne démarre avant que ses buffers atteignent le minimum."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.warmup_barrier import BarriereWarmup   # noqa: E402


def test_bloque_tant_que_buffer_insuffisant():
    b = BarriereWarmup()
    b.exiger("strat1", buffer="prix", minimum=3)
    b.observer("strat1", buffer="prix", n=2)
    assert b.pret("strat1")["pret"] is False
    b.observer("strat1", buffer="prix", n=1)
    assert b.pret("strat1")["pret"] is True


def test_plusieurs_buffers():
    b = BarriereWarmup()
    b.exiger("s", buffer="prix", minimum=1)
    b.exiger("s", buffer="vol", minimum=1)
    b.observer("s", buffer="prix", n=1)
    assert b.pret("s")["pret"] is False                   # vol pas encore rempli
    b.observer("s", buffer="vol", n=1)
    assert b.pret("s")["pret"] is True


def test_sans_exigence_non_pret():
    assert BarriereWarmup().pret("inconnue")["pret"] is False
