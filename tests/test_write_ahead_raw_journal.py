"""[pépite 276] write-ahead raw journal : brut journalisé durablement avant toute projection critique."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.capture.write_ahead_raw_journal import JournalWAL   # noqa: E402


def test_projection_refusee_avant_journal():
    j = JournalWAL()
    assert j.projection_autorisee("e1")["autorisee"] is False


def test_projection_autorisee_apres_journal():
    j = JournalWAL()
    j.journaliser("e1", {"raw": 1})
    assert j.projection_autorisee("e1")["autorisee"] is True


def test_ordre_rejeu():
    j = JournalWAL()
    j.journaliser("e1"); j.journaliser("e2"); j.journaliser("e1")   # doublon ignoré
    assert j.rejouer() == ["e1", "e2"]
