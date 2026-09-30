"""[pépite 237] episode-close reconciliation : CLOSED seulement si ordres+fills+ledger convergent."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.episode_close_reconciliation import peut_clore   # noqa: E402


def test_convergent_au_residu_zero():
    r = peut_clore(position_depuis_ordres=0.0, position_depuis_fills=0.0, position_ledger=0.0)
    assert r["peut_clore"] is True


def test_vues_divergentes():
    r = peut_clore(position_depuis_ordres=0.0, position_depuis_fills=0.1, position_ledger=0.0)
    assert r["peut_clore"] is False and r["convergent"] is False


def test_residu_non_nul():
    r = peut_clore(position_depuis_ordres=0.5, position_depuis_fills=0.5, position_ledger=0.5)
    assert r["peut_clore"] is False and r["au_residu_attendu"] is False
