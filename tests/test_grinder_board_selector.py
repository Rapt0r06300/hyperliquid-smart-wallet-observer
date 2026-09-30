"""Contrat de la sélection grinder sur le board: exits protégés, entrées classées/capées."""

from __future__ import annotations

from types import SimpleNamespace as NS

from hl_observer.integration.grinder_board_selector import (
    maybe_select_by_unified_board,
    select_orders_by_board,
)


def _order(coin, side="LONG", action="OPEN", otype="PAPER_MARKET"):
    return NS(coin=coin, side=side, action=action, order_type=otype)


def _be(coin, power):
    return NS(coin=coin, side="LONG", strategy="X", power_score=power, net_edge_bps=power / 2)


def test_exits_are_never_dropped():
    orders = [_order("BTC"), _order("ETH", action="CLOSE"), _order("SOL", otype="PAPER_CLOSE_SIGNAL")]
    kept = select_orders_by_board(orders, [_be("BTC", 80)], max_new_entries=0)   # cap 0 entrées
    coins = {o.coin for o in kept}
    assert "ETH" in coins and "SOL" in coins        # les 2 exits gardés malgré cap 0
    assert "BTC" not in coins                        # l'entrée est capée


def test_entries_ranked_by_board_power_and_capped():
    orders = [_order("BTC"), _order("ETH"), _order("SOL")]
    board = [_be("SOL", 90), _be("BTC", 70), _be("ETH", 40)]
    kept = select_orders_by_board(orders, board, max_new_entries=2)
    assert [o.coin for o in kept] == ["SOL", "BTC"]  # les 2 meilleures par power, dans l'ordre


def test_require_board_match_drops_unlisted_coins():
    orders = [_order("BTC"), _order("DOGE")]
    board = [_be("BTC", 60)]
    kept = select_orders_by_board(orders, board, require_board_match=True)
    assert [o.coin for o in kept] == ["BTC"]         # DOGE pas dans le board -> abandonné


def test_flag_off_is_noop():
    orders = [_order("BTC"), _order("ETH")]
    out = maybe_select_by_unified_board(orders, env={})   # flag absent
    assert out == orders                              # aucune sélection sans activation


def test_flag_on_selects_from_built_board():
    orders = [_order("HYPE"), _order("BTC")]
    distilled = [NS(coin="HYPE", side="LONG", edge_remaining_bps=35, event_time_ms=1000, liquidity_score=0.9)]
    out = maybe_select_by_unified_board(
        orders, distilled_opportunities=distilled, now_ms=2000,
        env={"HYPERSMART_GRINDER_UNIFIED_SELECTION": "1", "HYPERSMART_GRINDER_REQUIRE_BOARD_MATCH": "1"},
    )
    assert [o.coin for o in out] == ["HYPE"]          # seul HYPE est dans le board -> seul gardé
