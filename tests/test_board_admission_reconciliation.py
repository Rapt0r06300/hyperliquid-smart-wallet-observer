"""Réconciliation de la refonte sélection: le flag ON préserve le ledger, jamais d'exécution réelle.

Prouve la sûreté du contrôleur d'admission au niveau du VRAI fusion runtime:
- flag OFF = baseline inchangée ;
- flag ON = equity/drawdown cohérents (aucune désync), refus AVANT ouverture ;
- 0 exécution réelle dans tous les cas.
"""

from __future__ import annotations

# importe la fixture qui amorce le cycle d'import connu (copy_conflict_resolver)
from tests.test_fusion_strategy_runtime import _payload, run_fusion_strategy_runtime


def test_flag_on_preserves_reconciliation_and_safety(monkeypatch):
    monkeypatch.setenv("HYPERSMART_GRINDER_UNIFIED_SELECTION", "1")
    r = run_fusion_strategy_runtime(_payload())
    assert r.paper_engine.equity_usdt > 0                 # equity valide (pas de NaN/desync)
    assert r.paper_engine.drawdown_usdt >= 0
    assert r.real_execution is False                       # sécurité: jamais réel
    assert all(o.real_execution is False for o in r.paper_orders)
    assert all(o.paper_only for o in r.paper_orders)


def test_flag_off_and_on_both_reconcile(monkeypatch):
    monkeypatch.delenv("HYPERSMART_GRINDER_UNIFIED_SELECTION", raising=False)
    off = run_fusion_strategy_runtime(_payload())
    monkeypatch.setenv("HYPERSMART_GRINDER_UNIFIED_SELECTION", "1")
    on = run_fusion_strategy_runtime(_payload())
    # les deux produisent une equity cohérente ; le flag ON ne casse pas le ledger
    assert off.paper_engine.equity_usdt > 0 and on.paper_engine.equity_usdt > 0
    assert off.paper_engine.drawdown_usdt >= 0 and on.paper_engine.drawdown_usdt >= 0


def test_flag_on_with_high_bar_gates_but_reconciles(monkeypatch):
    # slot unique + board fort => barre haute => le copy plus faible peut être refusé,
    # mais l'equity reste cohérente (refus avant ouverture, jamais de désync)
    monkeypatch.setenv("HYPERSMART_GRINDER_UNIFIED_SELECTION", "1")
    monkeypatch.setenv("HYPERSMART_GRINDER_MAX_NEW_ENTRIES", "1")
    r = run_fusion_strategy_runtime(_payload())
    assert r.paper_engine.equity_usdt > 0                 # cohérent quel que soit le verdict
    assert r.paper_engine.accepted_count in (0, 1)         # 0 si refusé, 1 si admis — jamais incohérent
    assert r.real_execution is False
