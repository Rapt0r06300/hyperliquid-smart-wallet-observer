"""ISOLATION DES TESTS dYdX — corrige un bug d'isolation trouve a l'audit du 2026-07-11.

`DydxLiveObserver.__init__` appelle `_bootstrap_market_side_performance()`, qui lit le VRAI
journal de decisions du runtime (`decision_log.tail(event_type="PAPER_CLOSE")`). Consequence :
un observateur "neuf" cree dans un test heritait de l'historique REEL de la machine. Sur le poste
de Flo (qui a des pertes reelles sur ETH-USD LONG), le garde-fou `MARKET_SIDE_EDGE_AFTER_LOSS`
refusait alors TOUS les signaux des tests (positions_opened=0) -- alors que le meme test passait
sur une machine vierge. Un test dont le resultat depend de l'historique de la machine ne vaut rien.

On neutralise donc UNIQUEMENT le bootstrap depuis le disque. Le garde-fou lui-meme reste actif :
les tests qui veulent le declencher enregistrent leurs propres pertes via _record_market_side_outcome.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_history_bootstrap(request, monkeypatch):
    if "bootstrap" in request.node.name:
        return          # ce test verifie EXPRESSEMENT le bootstrap (avec son propre journal)
    monkeypatch.setattr(
        "hyper_smart_observer.dydx_v4.live_observer.DydxLiveObserver."
        "_bootstrap_market_side_performance",
        lambda self: None,
        raising=True,
    )
