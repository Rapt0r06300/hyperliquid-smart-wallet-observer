"""[COPY-VAULT lot2 #37] reconnect overlap backfill : fenêtre qui commence AVANT le checkpoint."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.reconnect_overlap_backfill import fenetre_backfill   # noqa: E402


def test_chevauchement():
    r = fenetre_backfill(10_000.0, overlap_ms=5000.0)
    assert r["debut_ms"] == 5000.0 and r["debut_ms"] < r["checkpoint_ms"]


def test_overlap_par_defaut():
    r = fenetre_backfill(10_000.0)
    assert r["debut_ms"] < 10_000.0


def test_checkpoint_invalide():
    assert fenetre_backfill(None)["debut_ms"] == "UNMEASURABLE"
