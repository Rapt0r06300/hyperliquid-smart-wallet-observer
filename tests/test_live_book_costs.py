"""LE GATE DE LIQUIDITÉ VALIDAIT CONTRE UN CARNET IMAGINAIRE (2026-07-11) — P2-2.

LE BUG, ET SA SIGNATURE DEVENUE FAMILIÈRE : **la capacité existait, l'interrupteur était éteint.**

`l2_snapshot_cache` sait interroger le carnet L2 réel et en tirer le VRAI spread et le VRAI
slippage. Mais **aucun des deux flags n'était posé dans les launchers** :

    HYPERSMART_V26_BOOK_POLLER      → le carnet n'était JAMAIS collecté
    HYPERSMART_V26_LIVE_BOOK_COSTS  → et jamais consommé

Conséquence : **tous** les gates de liquidité et de coût tournaient sur des constantes —
spread 6 bps, slippage 6 bps, profondeur 50 000 $ — **les mêmes pour BTC que pour un meme coin
illiquide**. Un gate de liquidité qui juge une liquidité inventée ne protège de rien.

Exactement le même schéma que le Grinder (flags absents) et que l'edge fabriqué (chiffre inventé).
**Trois fois la même maladie : le code sait faire, personne ne le branche.**

Règle du brief (Phase 6) : un repli est autorisé, mais il doit être **EXPLICITEMENT MARQUÉ** —
jamais substitué en silence par une valeur favorable.

Aucun ordre réel.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ les flags sont posés

def _ps1() -> str:
    return (RACINE / "tools" / "start_hypersmart_simulation.ps1").read_text(
        encoding="utf-8", errors="ignore"
    )


def test_the_book_poller_is_actually_switched_on():
    """SANS CE FLAG, LE CARNET N'EST JAMAIS COLLECTÉ. Le module existe, il ne tourne pas."""
    assert re.search(r'"HYPERSMART_V26_BOOK_POLLER",\s*"1"', _ps1()), (
        "le poller de carnet est éteint : aucune donnée L2 ne sera jamais collectée"
    )


def test_the_live_book_costs_are_actually_consumed():
    """Collecter le carnet sans le consommer ne sert à RIEN. Les deux flags vont ensemble."""
    assert re.search(r'"HYPERSMART_V26_LIVE_BOOK_COSTS",\s*"1"', _ps1()), (
        "le carnet est collecté mais jamais lu : les gates tournent toujours sur des constantes"
    )


# ------------------------------------------------------------------ le repli est MARQUÉ

def test_a_fallback_is_never_silent():
    """LE CŒUR. Sans carnet frais, on retombe sur des constantes — mais on le DIT.
    Une donnée absente remplacée en silence par une valeur favorable, c'est une donnée fabriquée."""
    import hl_observer.strategies.fusion_runtime  # noqa: F401  (ordre d'import applicatif)
    from hl_observer.paper_trading.fusion_paper_engine_adapter import _live_book_costs

    spread, slip, est_reel = _live_book_costs("UN_COIN_SANS_CARNET")
    assert est_reel is False, "un repli se déclare comme tel"
    assert spread > 0 and slip > 0


def test_the_real_book_is_used_when_available(monkeypatch):
    """Quand le carnet EST là, ce sont SES chiffres qui décident — pas les constantes."""
    import hl_observer.strategies.fusion_runtime  # noqa: F401
    from hl_observer.collection import l2_snapshot_cache
    from hl_observer.paper_trading import fusion_paper_engine_adapter as ad

    monkeypatch.setenv("HYPERSMART_V26_LIVE_BOOK_COSTS", "1")
    monkeypatch.setattr(l2_snapshot_cache, "live_costs_for", lambda coin, *a, **k: (1.7, 2.3))

    spread, slip, est_reel = ad._live_book_costs("BTC")
    assert est_reel is True
    assert spread == pytest.approx(1.7)
    assert slip == pytest.approx(2.3)
    # et surtout : ce ne sont PLUS les constantes de 6.0
    assert spread != 6.0 and slip != 6.0


def test_a_broken_cache_falls_back_without_crashing(monkeypatch):
    """Un cache qui plante ne doit ni bloquer le bot, ni faire passer une donnée fausse
    pour une donnée réelle."""
    import hl_observer.strategies.fusion_runtime  # noqa: F401
    from hl_observer.collection import l2_snapshot_cache
    from hl_observer.paper_trading import fusion_paper_engine_adapter as ad

    def _boom(*a, **k):
        raise RuntimeError("cache indisponible")

    monkeypatch.setattr(l2_snapshot_cache, "live_costs_for", _boom)
    spread, slip, est_reel = ad._live_book_costs("BTC")
    assert est_reel is False, "un plantage ne doit JAMAIS être présenté comme un carnet réel"
    assert spread > 0 and slip > 0


# ------------------------------------------------------------------ le carnet distingue les marchés

def test_two_different_coins_can_have_different_costs(monkeypatch):
    """LE FOND DU PROBLÈME : avant, BTC et un meme coin illiquide avaient EXACTEMENT le même
    spread et la même profondeur. Un carnet réel les distingue — c'est tout l'intérêt."""
    import hl_observer.strategies.fusion_runtime  # noqa: F401
    from hl_observer.collection import l2_snapshot_cache
    from hl_observer.paper_trading import fusion_paper_engine_adapter as ad

    carnets = {"BTC": (0.8, 1.0), "MEMECOIN": (35.0, 60.0)}
    monkeypatch.setenv("HYPERSMART_V26_LIVE_BOOK_COSTS", "1")
    monkeypatch.setattr(l2_snapshot_cache, "live_costs_for",
                        lambda coin, *a, **k: carnets.get(str(coin).upper()))

    btc = ad._live_book_costs("BTC")
    meme = ad._live_book_costs("MEMECOIN")
    assert btc[0] < meme[0], "le meme coin doit coûter BEAUCOUP plus cher que BTC"
    assert btc[1] < meme[1]
    assert btc[2] is True and meme[2] is True
