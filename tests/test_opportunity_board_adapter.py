"""Contrat de l'adaptateur fusion-result -> tableau d'opportunités unifié."""

from __future__ import annotations

from types import SimpleNamespace as NS

from hl_observer.integration.opportunity_board_adapter import (
    board_from_fusion_result,
    board_payload_from_fusion_result,
)


def _result(distilled=(), triangular=(), funding=()):
    return NS(
        distilled_opportunity_report=NS(opportunities=list(distilled)),
        triangular_opportunities=list(triangular),
        funding_signals=list(funding),
    )


def test_mixes_all_three_strategies_on_common_scale():
    r = _result(
        distilled=[NS(coin="HYPE", side="LONG", edge_remaining_bps=34, event_time_ms=1000,
                      liquidity_score=0.9, leader_score=88)],
        triangular=[NS(accepted=True, net_edge_bps=18, cycle=NS(coins=["BTC", "ETH", "USDC"]))],
        funding=[NS(coin="SOL", side="SHORT", net_edge_bps=26, liquidity_score=0.7)],
    )
    board = board_from_fusion_result(r, now_ms=2000)
    strategies = {e.strategy for e in board}
    assert strategies == {"DISTILLED", "ARBITRAGE", "FUNDING_ARB"}    # les 3 fusionnées
    assert board[0].strategy == "DISTILLED"                           # meilleur edge net (34) en tête
    assert board[0].power_score >= board[-1].power_score


def test_ignores_candidates_without_edge_and_unaccepted_arb():
    r = _result(
        distilled=[NS(coin="X", side="LONG", edge_remaining_bps=None, event_time_ms=1000)],  # pas d'edge -> ignoré
        triangular=[NS(accepted=False, net_edge_bps=50, cycle=NS(coins=["A"]))],              # non accepté -> ignoré
        funding=[NS(coin="SOL", side="LONG")],                                                # pas d'edge -> ignoré
    )
    assert board_from_fusion_result(r, now_ms=2000) == []             # rien d'inventé


def test_stale_distilled_dropped_by_floor():
    r = _result(distilled=[NS(coin="HYPE", side="LONG", edge_remaining_bps=40,
                              event_time_ms=0, liquidity_score=0.9)])
    # âge = now(99s) - 0 = 99s > 30s -> plancher fraîcheur -> éliminé
    assert board_from_fusion_result(r, now_ms=99_000) == []


def test_payload_is_serializable_for_dashboard():
    r = _result(funding=[NS(coin="SOL", side="SHORT", net_edge_bps=26, liquidity_score=0.7)])
    p = board_payload_from_fusion_result(r, now_ms=1000)
    assert isinstance(p["entries"], list) and p["entries"][0]["strategy"] == "FUNDING_ARB"
    assert p["summary"]["total"] == 1 and p["summary"]["by_strategy"]["FUNDING_ARB"] == 1


def test_empty_result_empty_board():
    assert board_from_fusion_result(_result(), now_ms=1000) == []
    assert board_payload_from_fusion_result(_result(), now_ms=1000)["summary"]["total"] == 0
