"""[pépite 208] working-order reconciliation : divergences classées (fantômes / orphelins / appariés)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.working_order_reconciliation import reconcilier   # noqa: E402


def test_classification():
    r = reconcilier(["o1", "o2", "o3"], ["o2", "o3", "o4"])
    assert r["fantomes_local_seulement"] == ["o1"]       # actif chez nous, pas a la source
    assert r["orphelins_source_seulement"] == ["o4"]     # actif source, pas chez nous
    assert r["apparies"] == ["o2", "o3"] and r["n_divergences"] == 2


def test_coherent():
    assert reconcilier(["o1"], ["o1"])["coherent"] is True


def test_tout_diverge():
    r = reconcilier(["a"], ["b"])
    assert r["coherent"] is False
