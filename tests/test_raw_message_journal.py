"""[DATA lot2 #66] raw-message journal : messages bruts journalisés avant parsing, ordre préservé."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.raw_message_journal import JournalBrut   # noqa: E402


def test_ordre_preserve():
    j = JournalBrut()
    j.journaliser(b"msg1", receipt_ts_ms=1.0)
    j.journaliser(b"msg2", receipt_ts_ms=2.0)
    rejeu = j.rejouer()
    assert [m["brut"] for m in rejeu] == [b"msg1", b"msg2"] and j.taille() == 2


def test_journal_non_mutable():
    j = JournalBrut()
    j.journaliser(b"m")
    j.rejouer().append({"brut": b"hack"})                # mutation de la copie
    assert j.taille() == 1


def test_receipt_ts_conserve():
    j = JournalBrut()
    j.journaliser(b"m", receipt_ts_ms=42.0)
    assert j.rejouer()[0]["receipt_ts_ms"] == 42.0
