"""[lot2 #98] recorder séparé du moteur : enfiler est non bloquant, le drain se fait à part."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.separate_recorder_process import RecorderDecouple   # noqa: E402


def test_enfiler_non_bloquant():
    r = RecorderDecouple(capacite=10)
    assert r.enfiler({"x": 1})["depose"] is True
    assert r.enfiler({"x": 2})["en_attente"] == 2


def test_file_pleine_drop_compte():
    r = RecorderDecouple(capacite=1)
    r.enfiler({"x": 1})
    out = r.enfiler({"x": 2})
    assert out["depose"] is False and out["raison"] == "FILE_PLEINE_DROP" and r.perdus == 1


def test_drainer():
    r = RecorderDecouple(capacite=10)
    r.enfiler({"x": 1})
    r.enfiler({"x": 2})
    d = r.drainer(lot=1)
    assert d["ecrits"] == 1 and d["reste"] == 1
