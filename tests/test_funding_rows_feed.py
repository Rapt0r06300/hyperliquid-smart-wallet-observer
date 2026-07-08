"""Fix cause racine: le heartbeat alimente funding_rows depuis le cache de taux.

Sans ça, funding_rows restait [] et le funding-arb ne pouvait jamais ouvrir de paire.
"""

from __future__ import annotations

import time

from hl_observer.funding import funding_runtime_cache as cache
from hl_observer.runtime.fusion_heartbeat_input import _build_funding_rows


def test_build_funding_rows_reads_cache():
    cache._store.clear()
    # simule le poller qui pousse des taux (horodatages recents, fenetre 24h)
    now = time.time()
    for i in range(10):
        cache.push("HYPE", 0.0005, ts=now - (10 - i) * 3600)
    rows = _build_funding_rows({"HYPE", "BTC"})
    by = {r["coin"]: r for r in rows}
    assert "HYPE" in by and len(by["HYPE"]["rates"]) == 10   # historique transmis
    assert "BTC" not in by                                    # pas d'historique -> absent (honnête)


def test_empty_cache_returns_empty_honestly():
    cache._store.clear()
    assert _build_funding_rows({"HYPE"}) == []                # vide = état honnête, jamais inventé


def test_heartbeat_starts_funding_poller(monkeypatch):
    # AUDIT 2026-07-08 — régression du trou critique: le heartbeat DOIT démarrer
    # le poller à chaque passage (sinon le cache reste vide et funding-arb muet).
    import hl_observer.funding.funding_poller as poller

    calls = {"n": 0}

    def _spy(env=None):
        calls["n"] += 1
        return True

    monkeypatch.setattr(poller, "ensure_started", _spy)
    cache._store.clear()
    _build_funding_rows({"HYPE"})
    assert calls["n"] == 1                                     # poller démarré par le heartbeat
