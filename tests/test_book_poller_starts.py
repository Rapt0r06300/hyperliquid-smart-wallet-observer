"""LE POLLER DE CARNET DOIT DEMARRER SUR LE CHEMIN LIVE (2026-07-12).

LE BUG, ET IL EST HUMILIANT :

Le 2026-07-08, on a corrige EXACTEMENT ce probleme pour le poller de FUNDING. Le commentaire est
encore dans `fusion_heartbeat_input.py` :

    « TROU CRITIQUE corrige: le poller n'avait AUCUN point de demarrage sur le chemin live
      (son seul appel etait derriere un autre flag non active) »

On a repare une jambe, et on a laisse l'autre exactement dans l'etat qu'on venait de denoncer.
Le poller de CARNET L2 n'avait qu'un seul point de demarrage :

    v26_entry_vetos.apply_v26_entry_vetos:294
        if _flag("HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE", False, env) and coin_known:
            ...
            _book_start(env)          # <-- DERRIERE un flag ABSENT DU LAUNCHER => False

Resultat, verifie sur 12 h de run reel : `funding.jsonl` grossit (7 Mo), `l2_book.jsonl` n'existe
meme pas. Et sans carnet : `live_costs_for()` ne rend rien, spread/slippage/profondeur retombent
sur des CONSTANTES, et le market making est INTESTABLE.

Aucun ordre reel.
"""
from __future__ import annotations

import inspect

from hl_observer.collection import l2_snapshot_cache
from hl_observer.runtime import fusion_heartbeat_input


def test_the_book_poller_is_started_from_the_LIVE_path_not_behind_a_dead_flag():
    """LE TEST QUI COMPTE. Le demarrage du poller carnet doit vivre dans le heartbeat live,
    au meme endroit que le poller de funding -- pas derriere un flag que personne n'allume."""
    src = inspect.getsource(fusion_heartbeat_input)
    assert "l2_snapshot_cache import ensure_started" in src, (
        "le poller de carnet n'est PAS demarre depuis le chemin live : il ne collectera rien"
    )


def test_both_pollers_start_from_the_SAME_place():
    """L'asymetrie est le bug : le funding demarrait ici, le carnet non. Les deux, ou aucun."""
    src = inspect.getsource(fusion_heartbeat_input)
    assert "funding_poller import ensure_started" in src
    assert "l2_snapshot_cache import ensure_started" in src


def test_starting_the_poller_is_a_NO_OP_when_the_flag_is_off(monkeypatch):
    """Demarrer n'est pas forcer : sans HYPERSMART_V26_BOOK_POLLER, aucun thread, aucun reseau."""
    monkeypatch.delenv("HYPERSMART_V26_BOOK_POLLER", raising=False)
    monkeypatch.setattr(l2_snapshot_cache, "_started", False, raising=False)
    assert l2_snapshot_cache.ensure_started({}) is False


def test_it_starts_when_the_flag_is_on(monkeypatch):
    demarres = []
    monkeypatch.setattr(l2_snapshot_cache, "_started", False, raising=False)

    class _FauxThread:
        def __init__(self, **kw):
            demarres.append(kw.get("name"))

        def start(self):
            pass

    monkeypatch.setattr(l2_snapshot_cache.threading, "Thread",
                        lambda *a, **kw: _FauxThread(**kw))
    assert l2_snapshot_cache.ensure_started({"HYPERSMART_V26_BOOK_POLLER": "1"}) is True
    assert demarres == ["v26-book-poller"]


def test_starting_twice_never_spawns_two_threads(monkeypatch):
    n = []
    monkeypatch.setattr(l2_snapshot_cache, "_started", False, raising=False)

    class _FauxThread:
        def __init__(self, **kw):
            n.append(1)

        def start(self):
            pass

    monkeypatch.setattr(l2_snapshot_cache.threading, "Thread", lambda *a, **kw: _FauxThread(**kw))
    env = {"HYPERSMART_V26_BOOK_POLLER": "1"}
    l2_snapshot_cache.ensure_started(env)
    l2_snapshot_cache.ensure_started(env)
    assert len(n) == 1, "idempotent : un seul thread, jamais deux"
