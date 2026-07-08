"""Contrat de l'enrichissement funding -> opportunités avec edge (échelle board)."""

from __future__ import annotations

from types import SimpleNamespace as NS

from hl_observer.funding.funding_opportunity import enrich_funding_with_edge


def _sig(coin, decision="FUNDING_SPIKE"):
    return NS(coin=coin, decision=decision, z_score=2.5, reason=None)


def test_enriches_spike_signals_with_edge():
    ops = enrich_funding_with_edge([_sig("SOL"), _sig("BTC")], {"SOL": 2.5, "BTC": 3.0})
    by = {o.coin: o for o in ops}
    assert by["SOL"].net_edge_bps == 14.0 and by["SOL"].side == "SHORT"     # 2.5*8-6
    assert by["BTC"].net_edge_bps == 18.0                                    # 3.0*8-6


def test_ignores_missing_rate_and_non_spike_and_weak():
    ops = enrich_funding_with_edge(
        [_sig("SOL"), _sig("ETH", decision="NO_TRADE"), _sig("DOGE")],
        {"SOL": 2.5, "DOGE": 0.2},     # ETH pas de taux, DOGE trop faible
    )
    coins = {o.coin for o in ops}
    assert coins == {"SOL"}            # ETH (non-spike) + DOGE (edge<0) + pas de taux -> ignorés


def test_apr_gate_filters():
    # 2.5 bps/h => APR 219% ; gate 300% => refusé
    assert enrich_funding_with_edge([_sig("SOL")], {"SOL": 2.5}, min_apr_pct=300.0) == []
    assert len(enrich_funding_with_edge([_sig("SOL")], {"SOL": 2.5}, min_apr_pct=100.0)) == 1


def test_empty_inputs():
    assert enrich_funding_with_edge([], {"SOL": 2.5}) == []
    assert enrich_funding_with_edge([_sig("SOL")], None) == []
