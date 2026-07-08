"""Contrat du contrôleur d'admission board (barre marginale, compétition slots)."""

from __future__ import annotations

from types import SimpleNamespace as NS

from hl_observer.integration.board_admission import (
    admission_floor_power,
    admits_candidate,
    candidate_power,
    is_admitted,
)


def _be(power):
    return NS(power_score=power, net_edge_bps=power / 2)


def test_floor_is_zero_when_slots_available():
    board = [_be(80), _be(60)]
    assert admission_floor_power(board, max_slots=5) == 0.0     # 2 opp, 5 slots -> place libre
    assert admission_floor_power([], max_slots=5) == 0.0


def test_floor_is_marginal_slot_power_when_full():
    board = [_be(90), _be(70), _be(50), _be(30)]
    assert admission_floor_power(board, max_slots=3) == 50.0    # 3e meilleur = barre


def test_strong_candidate_admitted_weak_rejected_when_full():
    board = [_be(90), _be(70), _be(50)]                          # 3 slots pleins, barre 50
    strong = admits_candidate(board, max_slots=3, coin="SOL", side="LONG",
                              net_edge_bps=40, signal_age_ms=1000, consensus_wallets=3, liquidity_score=0.9)
    weak = admits_candidate(board, max_slots=3, coin="X", side="LONG",
                            net_edge_bps=9, signal_age_ms=1000, consensus_wallets=1, liquidity_score=0.35)
    assert strong["admitted"] is True and strong["candidate_power"] >= strong["floor_power"]
    assert weak["admitted"] is False


def test_floor_failure_never_admitted():
    # edge sous le plancher dur (8 bps) -> power 0 -> jamais admis, meme barre 0
    assert is_admitted(candidate_power(coin="X", side="LONG", net_edge_bps=4, signal_age_ms=1000), 0.0) is False


def test_slots_available_admits_any_positive_power():
    board = [_be(90)]                                            # 1 opp, 5 slots -> barre 0
    r = admits_candidate(board, max_slots=5, coin="SOL", side="LONG",
                         net_edge_bps=20, signal_age_ms=1000, consensus_wallets=2, liquidity_score=0.8)
    assert r["floor_power"] == 0.0 and r["admitted"] is True
