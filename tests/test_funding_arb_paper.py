"""Funding-arb paper (mode grinder brique 2) — règles distillées du repo 32.

Vérifie: entrée sur edge fort et stable, refus spike/historique court/edge
faible/prix manquant, accrual horaire correct, sortie sur edge effondré avec
PnL net = funding - coûts des deux jambes, caps de paires, flags paper.
"""

from __future__ import annotations

from hl_observer.funding.funding_arb_paper import (

    FundingArbConfig,
    evaluate_funding_arb,
    funding_arb_paper_enabled,
)

CFG = FundingArbConfig(
    min_entry_edge_bps_per_hour=2.5,
    exit_edge_bps_per_hour=0.65,
    leg_notional_usdt=25.0,
    max_pairs=2,
    max_total_notional_usdt=100.0,
)

STABLE_HIGH = [0.00049, 0.00051, 0.0005, 0.00052, 0.00048, 0.0005, 0.00051, 0.00049, 0.0005, 0.00052, 0.00048, 0.0005]  # ~5 bps/h
STABLE_LOW = [0.00001] * 12  # 0.1 bps/h
SPIKY = [0.00005] * 11 + [0.002]  # dernier point aberrant


def _report(rows, positions=(), now_ms=10_000_000, cfg=CFG, prices=None):
    return evaluate_funding_arb(
        funding_rows=tuple(rows),
        prices=prices if prices is not None else {"HYPE": 70.0, "BTC": 50_000.0, "ETH": 3_000.0},
        positions=tuple(positions),
        now_ms=now_ms,
        config=cfg,
    )


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("HYPERSMART_FUNDING_ARB_PAPER", raising=False)
    assert funding_arb_paper_enabled() is False


def test_opens_pair_on_strong_stable_funding():
    report = _report([{"coin": "HYPE", "rates": STABLE_HIGH}])
    assert report.open_pairs == 1
    pos = report.positions[0]
    assert pos.receiving_side == "SHORT"  # funding positif: le short encaisse
    assert pos.paper_only is True and pos.real_execution is False
    assert any(e.action == "OPEN" for e in report.events)
    assert report.total_notional_usdt == 50.0  # 1 paire = 2 jambes x 25 USDT


def test_refuses_spike_short_history_small_edge_and_missing_price():
    report = _report(
        [
            {"coin": "HYPE", "rates": SPIKY},
            {"coin": "BTC", "rates": STABLE_HIGH[:4]},
            {"coin": "ETH", "rates": STABLE_LOW},
            {"coin": "SOL", "rates": STABLE_HIGH},
        ],
        prices={"HYPE": 70.0, "BTC": 50_000.0, "ETH": 3_000.0, "SOL": 0.0},
    )
    reasons = {e.coin: e.reason for e in report.events if e.action == "NO_TRADE"}
    assert reasons["HYPE"] == "FUNDING_SPIKE_UNSTABLE"
    assert reasons["BTC"] == "FUNDING_HISTORY_TOO_SHORT"
    assert reasons["ETH"] == "FUNDING_EDGE_TOO_SMALL"
    assert reasons["SOL"] == "MARKET_PRICE_MISSING"
    assert report.open_pairs == 0


def test_accrues_hourly_funding_on_open_pair():
    first = _report([{"coin": "HYPE", "rates": STABLE_HIGH}], now_ms=0)
    assert first.open_pairs == 1
    later = _report([{"coin": "HYPE", "rates": STABLE_HIGH}], positions=first.positions, now_ms=2 * 3_600_000)
    accruals = [e for e in later.events if e.action == "ACCRUAL"]
    assert len(accruals) == 1
    expected = 25.0 * (5.0 / 10_000.0) * 2  # notional x 5 bps/h x 2h
    assert abs(accruals[0].amount_usdc - expected) < 0.002
    assert later.positions[0].accrued_funding_usdc > 0


def test_closes_pair_when_edge_collapses_with_honest_net_pnl():
    first = _report([{"coin": "HYPE", "rates": STABLE_HIGH}], now_ms=0)
    pos = first.positions[0]
    # 3h de funding accumulé puis le rate tombe à ~0: sortie attendue
    mid = _report([{"coin": "HYPE", "rates": STABLE_HIGH}], positions=(pos,), now_ms=3 * 3_600_000)
    dead = _report([{"coin": "HYPE", "rates": STABLE_HIGH[:-1] + [0.0]}], positions=mid.positions, now_ms=4 * 3_600_000)
    closes = [e for e in dead.events if e.action == "CLOSE"]
    assert len(closes) == 1
    assert closes[0].reason == "FUNDING_EDGE_COLLAPSED"
    assert closes[0].net_pnl_usdc is not None
    # net = accrued - entry_costs - close_costs, tous > 0 → net cohérent
    assert dead.realized_pnl_usdc == closes[0].net_pnl_usdc
    assert dead.open_pairs == 0


def test_max_pairs_cap_enforced():
    report = _report(
        [
            {"coin": "HYPE", "rates": STABLE_HIGH},
            {"coin": "BTC", "rates": [r * 1.2 for r in STABLE_HIGH]},
            {"coin": "ETH", "rates": [r * 1.1 for r in STABLE_HIGH]},
        ]
    )
    assert report.open_pairs == 2  # cap max_pairs=2
    assert any(e.reason == "MAX_PAIRS_REACHED" for e in report.events)


# ---------------------------------------------------------------------------------------------
# VERROU CARRY (2026-07-11) -- POURQUOI CES TESTS FORCENT UN FLAG.
#
# Ces tests verifient la MECANIQUE du moteur funding (accrual, caps, sortie, PnL). Pour cela, il
# faut qu'une position s'ouvre. Or depuis la mesure du 2026-07-11, le moteur REFUSE par defaut
# d'ouvrir une jambe NUE :
#
#     232 marches, 9 512 releves : funding median 0,125 bps/h contre ~35 bps/h de mouvement de
#     prix. Pour 1 bps de funding encaisse, une jambe nue subit ~281 bps de mouvement de prix.
#
# On active donc explicitement `HYPERSMART_FUNDING_ALLOW_UNHEDGED_LEG=1` : c'est un mode A/B
# ASSUME, PAS le comportement de production. Le defaut, lui, reste le REFUS -- et c'est
# `tests/test_funding_carry_economics.py` qui garde cette regle.
# ---------------------------------------------------------------------------------------------
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _autoriser_jambe_nue_pour_tester_la_mecanique(monkeypatch):
    """Mode A/B : on ouvre la vanne pour pouvoir tester l'interieur du moteur."""
    monkeypatch.setenv("HYPERSMART_FUNDING_ALLOW_UNHEDGED_LEG", "1")
