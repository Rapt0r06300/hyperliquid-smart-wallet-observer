"""E24 — budget de turnover : moins de trades, plus propres ; barre haute + budget glissant."""
from __future__ import annotations

from hl_observer.risk.budget_turnover import BudgetTurnover

H = 3_600_000


def test_edge_sous_la_barre_refuse():
    b = BudgetTurnover(max_trades=10, barre_edge_haute_bps=40.0)
    assert b.peut_trader(0, edge_net_bps=30.0) is False     # sous la barre haute
    assert b.peut_trader(0, edge_net_bps=45.0) is True      # au-dessus -> ok (budget libre)


def test_budget_epuise_refuse_meme_un_bon_edge():
    b = BudgetTurnover(max_trades=2, barre_edge_haute_bps=40.0)
    b.enregistrer(0)
    b.enregistrer(1 * H)
    assert b.peut_trader(2 * H, edge_net_bps=100.0) is False   # budget plein -> non malgre bon edge


def test_fenetre_glissante_libere_le_budget():
    b = BudgetTurnover(max_trades=1, fenetre_ms=24 * H, barre_edge_haute_bps=40.0)
    b.enregistrer(0)
    assert b.peut_trader(1 * H, 50.0) is False               # dans la fenetre -> plein
    assert b.peut_trader(25 * H, 50.0) is True               # 25h > 24h -> l'ancien sort, budget libre


def test_compte_dans_la_fenetre():
    b = BudgetTurnover(fenetre_ms=10 * H)
    b.enregistrer(0)
    b.enregistrer(5 * H)
    assert b.trades_dans_la_fenetre(6 * H) == 2
    assert b.trades_dans_la_fenetre(12 * H) == 1             # l'estampille a 0 est sortie
