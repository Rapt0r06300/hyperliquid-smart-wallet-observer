"""
Tests du moteur de découverte multi-sources de wallets.

100% déterministe. Aucun réseau. READ-ONLY / PAPER-ONLY.

Couvre: validation d'adresse (rejet tronquées), index dédupliqué/fusion,
parsing leaderboard/tape, sources injectables + robustesse, scoring/ranking,
gates « qualité d'exécution » du bot viral, intégration vers le FastScanner,
et absence de toute capacité d'ordre.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hyper_smart_observer.dydx_v4.wallet_harvester import (
    GATE_MIN_PROFIT_FACTOR,
    WalletHarvester,
    WalletIndex,
    extract_leaderboard_addresses,
    extract_tape_addresses,
    is_valid_address,
    leaderboard_source,
    passes_viral_gates,
    score_candidate,
    static_source,
    tape_source,
)

# Adresses complètes valides pour les tests
A = "dydx1" + "a" * 39
B = "dydx1" + "b" * 39
C_HEX = "0x" + "c" * 40


# --------------------------------------------------------------------------- #
# Validation d'adresse
# --------------------------------------------------------------------------- #
def test_is_valid_address():
    assert is_valid_address(A) is True
    assert is_valid_address(C_HEX) is True
    assert is_valid_address("") is False
    assert is_valid_address("dydx1" + "a" * 5) is False        # trop courte
    assert is_valid_address("0x" + "a" * 39) is False          # 39 != 40 hex
    assert is_valid_address("0xabcd...ef12") is False          # tronquée
    assert is_valid_address("dydx1abc…xyz") is False           # tronquée (…)
    assert is_valid_address(123) is False                      # pas une str


# --------------------------------------------------------------------------- #
# Index
# --------------------------------------------------------------------------- #
def test_index_observe_creates_and_merges():
    idx = WalletIndex()
    c1 = idx.observe(A, "leaderboard", now_ms=1000, metrics={"winrate": 0.6})
    assert c1 is not None
    assert len(idx) == 1
    assert c1.activity_count == 1
    assert c1.sources == {"leaderboard"}
    assert c1.first_seen_ms == 1000 and c1.last_seen_ms == 1000

    # 2e observation, autre source, plus tard, complète les métriques
    c2 = idx.observe(A, "tape", now_ms=5000, metrics={"profit_factor": 1.8})
    assert c2 is c1                       # même candidat fusionné
    assert len(idx) == 1
    assert c1.activity_count == 2
    assert c1.sources == {"leaderboard", "tape"}
    assert c1.first_seen_ms == 1000       # min conservé
    assert c1.last_seen_ms == 5000        # max mis à jour
    assert c1.winrate == 0.6 and c1.profit_factor == 1.8
    assert c1.has_metrics is True


def test_index_rejects_invalid_address():
    idx = WalletIndex()
    assert idx.observe("0xabc...def", "tape", now_ms=1000) is None
    assert idx.observe("", "tape", now_ms=1000) is None
    assert len(idx) == 0


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #
def test_extract_leaderboard_addresses():
    payload = {
        "leaderboard": [
            {"address": A, "pnl": 1000, "roi": 30, "winRate": 0.6, "profitFactor": 2.0, "trades": 50},
            {"user": B, "net_pnl_usdc": 500},
            {"foo": "bar"},  # pas d'adresse -> ignoré
        ]
    }
    out = extract_leaderboard_addresses(payload)
    assert len(out) == 2
    addr0, m0 = out[0]
    assert addr0 == A
    assert m0["winrate"] == 0.6 and m0["profit_factor"] == 2.0 and m0["trade_count"] == 50


def test_extract_tape_addresses_filters_invalid():
    trades = [
        {"user": A},
        {"maker": B, "taker": "0xshort...0"},
        {"address": "not-an-address"},
        "garbage",
    ]
    found = extract_tape_addresses(trades)
    assert A in found and B in found
    assert all(is_valid_address(x) for x in found)


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
def test_source_failure_is_isolated():
    def boom():
        raise RuntimeError("réseau coupé")

    src = leaderboard_source("lb", boom)
    assert src.harvest() == []  # ne lève jamais


def test_static_source():
    src = static_source("seed", [A, B])
    pairs = src.harvest()
    assert {p[0] for p in pairs} == {A, B}


# --------------------------------------------------------------------------- #
# Scoring & gates
# --------------------------------------------------------------------------- #
def test_passes_viral_gates():
    from hyper_smart_observer.dydx_v4.wallet_harvester import WalletCandidate

    good = WalletCandidate(address=A, winrate=0.6, profit_factor=2.0, trade_count=50)
    bad_wr = WalletCandidate(address=A, winrate=0.2, profit_factor=2.0, trade_count=50)
    bad_pf = WalletCandidate(address=A, winrate=0.6, profit_factor=1.0, trade_count=50)
    few = WalletCandidate(address=A, winrate=0.6, profit_factor=2.0, trade_count=3)
    unknown = WalletCandidate(address=A)  # pas de métriques -> passe (découverte)

    assert passes_viral_gates(good) is True
    assert passes_viral_gates(bad_wr) is False
    assert passes_viral_gates(bad_pf) is False
    assert passes_viral_gates(few) is False
    assert passes_viral_gates(unknown) is True
    assert GATE_MIN_PROFIT_FACTOR == 1.2


def test_score_quality_and_recency_ordering():
    from hyper_smart_observer.dydx_v4.wallet_harvester import WalletCandidate

    now = 10_000_000
    strong = WalletCandidate(
        address=A, sources={"leaderboard", "tape"}, last_seen_ms=now,
        activity_count=50, winrate=0.7, profit_factor=2.5, roi_pct=40,
    )
    weak = WalletCandidate(
        address=B, sources={"tape"}, last_seen_ms=now - 3_600_000,  # 1h -> récence ~0
        activity_count=1,
    )
    s_strong = score_candidate(strong, now)
    s_weak = score_candidate(weak, now)
    assert s_strong > s_weak
    assert s_strong > 0


# --------------------------------------------------------------------------- #
# Harvester
# --------------------------------------------------------------------------- #
def test_harvester_fanout_dedupe_and_rank():
    h = WalletHarvester(max_track=10)
    h.add_source(leaderboard_source("lb", lambda: {
        "leaderboard": [
            {"address": A, "winRate": 0.7, "profitFactor": 2.5, "trades": 40},
            {"address": B, "winRate": 0.1, "profitFactor": 0.8, "trades": 40},  # mauvais
        ]
    }))
    h.add_source(static_source("seed", [A, C_HEX]))  # A revu -> dédup

    new1 = h.harvest_once(now_ms=1000)
    assert new1 == 3                       # A, B, C_HEX (A compté une fois)
    assert len(h.index) == 3
    # A vu dans 2 sources
    assert h.index.get(A).activity_count == 2
    assert h.index.get(A).sources == {"lb", "seed"}

    new2 = h.harvest_once(now_ms=2000)
    assert new2 == 0                       # aucune nouvelle adresse
    assert len(h.index) == 3

    # B échoue aux gates (winrate 0.1, PF 0.8) -> exclu du ranking
    ranked = h.rank(now_ms=2000)
    addrs = [c.address for c in ranked]
    assert B not in addrs
    assert A in addrs and C_HEX in addrs
    # A (métriques fortes + multi-source) classé avant C_HEX (sans métriques)
    assert addrs.index(A) < addrs.index(C_HEX)


def test_harvester_top_for_scanner_shape():
    h = WalletHarvester(max_track=2)
    h.add_source(static_source("seed", [A, B, C_HEX]))
    h.harvest_once(now_ms=1000)
    top = h.top_for_scanner(now_ms=1000)
    assert len(top) == 2                   # borné par max_track
    assert all(isinstance(addr, str) and isinstance(score, float) for addr, score in top)


def test_harvester_failing_source_does_not_crash():
    h = WalletHarvester()

    def boom():
        raise RuntimeError("down")

    h.add_source(leaderboard_source("broken", boom))
    h.add_source(static_source("ok", [A]))
    assert h.harvest_once(now_ms=1000) == 1
    assert A in h.index


def test_harvester_stats():
    h = WalletHarvester()
    h.add_source(static_source("seed", [A]))
    h.harvest_once(now_ms=1000)
    s = h.stats()
    assert s["total_addresses"] == 1
    assert s["read_only"] is True and s["paper_only"] is True
    assert "seed" in s["sources"]


# --------------------------------------------------------------------------- #
# Intégration harvester -> FastScanner
# --------------------------------------------------------------------------- #
def test_harvester_feeds_fast_scanner():
    from hyper_smart_observer.dydx_v4.fast_scanner import FastScanner

    h = WalletHarvester(max_track=5)
    h.add_source(static_source("seed", [A, B, C_HEX]))
    h.harvest_once(now_ms=1000)

    scanner = FastScanner(ws_client=None, hot_capacity=5)
    scanner.track_wallets(h.top_for_scanner(now_ms=1000))  # ws=None -> pas de réseau
    # Les wallets sont bien dans le hot-set (abonnement no-op sans ws)
    assert len(scanner.hot) == 3
    assert A in scanner.hot.active()


# --------------------------------------------------------------------------- #
# Sécurité
# --------------------------------------------------------------------------- #
def test_harvester_has_no_execution_methods():
    h = WalletHarvester()
    forbidden = ("order", "sign", "submit", "place", "withdraw", "deposit",
                 "private_key", "mnemonic", "seed", "transfer", "buy", "sell")
    for name in [n for n in dir(h) if not n.startswith("__")]:
        low = name.lower()
        assert not any(tok in low for tok in forbidden), f"méthode interdite: {name}"


# --------------------------------------------------------------------------- #
# Source on-chain Cosmos (maximum d'adresses)
# --------------------------------------------------------------------------- #
class _FakeCosmos:
    """Faux client Cosmos: duck-typing sur scan_subaccounts (aucun réseau)."""

    def __init__(self, subs):
        self._subs = subs
        self.calls = 0

    def scan_subaccounts(self, **kwargs):
        self.calls += 1
        return self._subs


def test_cosmos_source_yields_addresses_and_balance():
    from hyper_smart_observer.dydx_v4.wallet_harvester import cosmos_source

    fake = _FakeCosmos([
        SimpleNamespace(address=A, usdc_balance=50_000.0),
        SimpleNamespace(address=B, usdc_balance=8_000.0),
    ])
    pairs = cosmos_source("cosmos", fake).harvest()
    by_addr = {a: m for a, m in pairs}
    assert A in by_addr and B in by_addr
    assert by_addr[A]["usdc_balance"] == 50_000.0


def test_harvester_cosmos_source_indexes_and_scores_balance():
    h = WalletHarvester()
    fake = _FakeCosmos([
        SimpleNamespace(address=A, usdc_balance=100_000.0),
        SimpleNamespace(address="0xbad...1", usdc_balance=1.0),  # tronquée -> rejetée
    ])
    h.add_cosmos_source(fake, min_usdc=1000)
    new = h.harvest_once(now_ms=1000)
    assert new == 1                       # l'adresse tronquée est rejetée par l'index
    assert h.index.get(A).usdc_balance == 100_000.0
    ranked = h.rank(now_ms=1000)
    assert ranked and ranked[0].address == A and ranked[0].score > 0


def test_score_includes_balance_component():
    from hyper_smart_observer.dydx_v4.wallet_harvester import WalletCandidate

    now = 1000
    with_bal = WalletCandidate(
        address=A, sources={"cosmos"}, last_seen_ms=now, activity_count=1,
        usdc_balance=100_000.0,
    )
    without = WalletCandidate(
        address=B, sources={"cosmos"}, last_seen_ms=now, activity_count=1,
    )
    assert score_candidate(with_bal, now) > score_candidate(without, now)
