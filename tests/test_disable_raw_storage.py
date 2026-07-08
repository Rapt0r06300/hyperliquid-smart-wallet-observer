"""Anti-bloat: HYPERSMART_DISABLE_RAW_STORAGE coupe les 3 stockages bruts.

Régression du crash observé (DB simulation gonflée à 29 Go -> corrompue) : les
payloads bruts (L2 books, leaderboards, fills) étaient stockés sans cap à chaque
poll. Ce flag les coupe d'un coup ; le ledger canonique n'en dépend pas.
"""

from __future__ import annotations

from hl_observer.config.loader import load_settings


def test_default_keeps_raw_storage(monkeypatch):
    monkeypatch.delenv("HYPERSMART_DISABLE_RAW_STORAGE", raising=False)
    s = load_settings()
    assert s.collection.store_raw_events is True                       # comportement inchangé par défaut


def test_flag_disables_all_three_raw_stores(monkeypatch):
    monkeypatch.setenv("HYPERSMART_DISABLE_RAW_STORAGE", "1")
    s = load_settings()
    assert s.collection.store_raw_events is False
    assert s.wallet_discovery.store_raw_discovery_payloads is False
    assert s.wallet_bootstrap.store_raw_source_payloads is False
