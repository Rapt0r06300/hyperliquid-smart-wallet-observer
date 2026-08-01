"""[pépite 277] atomic checkpoint : offset + state hash + dataset position commités atomiquement (tout ou rien)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.capture.atomic_checkpoint import commit   # noqa: E402


def test_commit_complet():
    r = commit(offset=12345, state_hash="abcd", dataset_position=99)
    assert r["commit"] is True and r["atomique"] is True and r["record"]["offset"] == 12345


def test_composant_manquant_refuse():
    r = commit(offset=12345, state_hash=None, dataset_position=99)
    assert r["commit"] is False and r["manquants"] == ["state_hash"]


def test_plusieurs_manquants():
    r = commit(offset=None, state_hash=None, dataset_position=1)
    assert set(r["manquants"]) == {"offset", "state_hash"}
