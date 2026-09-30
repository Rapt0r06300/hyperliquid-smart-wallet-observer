"""
Tests du scanner rapide multi-wallets dYdX v4.

100% déterministe. Aucun appel réseau. READ-ONLY / PAPER-ONLY.

Couvre: parsing horodatage, parsing fills subaccount, déduplication bornée,
hot-set borné (éviction), métriques de débit, fenêtre de fraîcheur (le bug du
PnL négatif), balayage REST injecté, et absence de toute capacité d'ordre.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hyper_smart_observer.dydx_v4.fast_scanner import (
    CHANNEL_SUBACCOUNTS,
    FastScanner,
    FillDeduper,
    HotWalletSet,
    ScannedFill,
    ThroughputMeter,
    parse_iso_to_ms,
    parse_subaccount_fills,
)

# Instant de référence dérivé de la fonction testée -> tests auto-cohérents,
# indépendants de la valeur epoch absolue (le défaut de _raw_fill utilise le
# même horodatage, donc l'arithmétique d'âge reste exacte).
BASE_ISO = "2026-06-12T00:00:00.000Z"
BASE_MS = parse_iso_to_ms(BASE_ISO)


# --------------------------------------------------------------------------- #
# Horodatage
# --------------------------------------------------------------------------- #
def test_parse_iso_to_ms_variants():
    from datetime import datetime, timezone

    # Valeur de référence calculée indépendamment (pas de constante codée en dur)
    expected = int(datetime(2026, 6, 12, tzinfo=timezone.utc).timestamp() * 1000)
    # ISO avec Z
    assert parse_iso_to_ms("2026-06-12T00:00:00.000Z") == expected
    # ISO avec offset explicite == même instant
    assert parse_iso_to_ms("2026-06-12T00:00:00+00:00") == expected
    # Déjà en millisecondes
    assert parse_iso_to_ms(expected) == expected
    # En secondes -> converti en ms
    assert parse_iso_to_ms(expected // 1000) == expected


def test_parse_iso_to_ms_invalid_returns_none():
    assert parse_iso_to_ms(None) is None
    assert parse_iso_to_ms("") is None
    assert parse_iso_to_ms("pas une date") is None
    assert parse_iso_to_ms(0) is None


# --------------------------------------------------------------------------- #
# Parsing fills
# --------------------------------------------------------------------------- #
def _raw_fill(**kw):
    base = {
        "id": "fill-1",
        "market": "BTC-USD",
        "side": "BUY",
        "size": "0.5",
        "price": "60000",
        "createdAt": "2026-06-12T00:00:00.000Z",
    }
    base.update(kw)
    return base


def test_parse_subaccount_fills_ok():
    now = BASE_MS + 1500  # 1.5 s après le fill
    contents = {"fills": [_raw_fill()]}
    fills = parse_subaccount_fills("0xabc", 0, contents, now)
    assert len(fills) == 1
    f = fills[0]
    assert f.market_id == "BTC-USD"
    assert f.side == "BUY"
    assert f.size == 0.5
    assert f.price == 60000.0
    assert f.age_ms == 1500
    assert f.notional_usdc == pytest.approx(30000.0)
    assert f.source == "WS"


def test_parse_subaccount_fills_skips_incomplete():
    now = BASE_MS
    contents = {
        "fills": [
            _raw_fill(id=""),                 # pas d'id
            _raw_fill(market=""),             # pas de marché
            _raw_fill(price="0"),             # prix invalide
            _raw_fill(size="0"),              # taille nulle
            _raw_fill(createdAt="garbage"),   # horodatage non parsable
            "not-a-dict",                     # type invalide
        ]
    }
    assert parse_subaccount_fills("0xabc", 0, contents, now) == []


def test_parse_subaccount_fills_bad_contents():
    assert parse_subaccount_fills("0xabc", 0, {}, 0) == []
    assert parse_subaccount_fills("0xabc", 0, {"fills": "x"}, 0) == []


# --------------------------------------------------------------------------- #
# Déduplication
# --------------------------------------------------------------------------- #
def test_dedupe_new_then_duplicate():
    d = FillDeduper(maxlen=10)
    assert d.add("a") is True
    assert d.add("a") is False
    assert "a" in d
    assert d.add("") is False


def test_dedupe_bounded_eviction():
    d = FillDeduper(maxlen=3)
    for fid in ["a", "b", "c"]:
        assert d.add(fid) is True
    # 'a' est évincé quand 'd' entre
    assert d.add("d") is True
    assert "a" not in d
    assert len(d) == 3
    # 'a' redevient "nouveau" car évincé de la mémoire
    assert d.add("a") is True


# --------------------------------------------------------------------------- #
# Hot wallet set
# --------------------------------------------------------------------------- #
def test_hotset_add_and_capacity_eviction():
    hot = HotWalletSet(capacity=2)
    added, removed = hot.observe("w1", 10.0, now_ms=1000)
    assert added == {"w1"} and removed == set()
    hot.observe("w2", 20.0, now_ms=1000)
    # w3 a un meilleur score que w1 -> w1 (plus faible) est évincé
    added, removed = hot.observe("w3", 30.0, now_ms=1000)
    assert added == {"w3"}
    assert removed == {"w1"}
    assert hot.active() == {"w2", "w3"}


def test_hotset_new_but_lowest_is_evicted_immediately():
    hot = HotWalletSet(capacity=1)
    hot.observe("strong", 100.0, now_ms=1000)
    # Nouveau wallet plus faible: il entre puis est immédiatement évincé,
    # donc rien à abonner et rien à désabonner.
    added, removed = hot.observe("weak", 1.0, now_ms=1000)
    assert added == set()
    assert removed == set()
    assert hot.active() == {"strong"}


def test_hotset_update_keeps_max_score():
    hot = HotWalletSet(capacity=5)
    hot.observe("w1", 10.0, now_ms=1000)
    added, removed = hot.observe("w1", 50.0, now_ms=2000)
    assert added == set() and removed == set()
    assert len(hot) == 1


def test_hotset_evict_stale():
    hot = HotWalletSet(capacity=5)
    hot.observe("w1", 10.0, now_ms=1000)
    hot.observe("w2", 10.0, now_ms=5000)
    removed = hot.evict_stale(older_than_ms=1000, now_ms=5000)
    assert removed == {"w1"}
    assert hot.active() == {"w2"}


# --------------------------------------------------------------------------- #
# Débit
# --------------------------------------------------------------------------- #
def test_throughput_median_and_rate():
    m = ThroughputMeter(window_s=10.0)
    for age in (100, 300, 200):
        m.record(age, monotonic_s=100.0)
    assert m.median_age_ms() == 200.0
    assert m.fills_per_second(now_s=100.0) == pytest.approx(0.3)


def test_throughput_window_trims_old_events():
    m = ThroughputMeter(window_s=10.0)
    m.record(100, monotonic_s=0.0)
    m.record(100, monotonic_s=100.0)  # bien après la fenêtre
    assert m.fills_per_second(now_s=100.0) == pytest.approx(0.1)


# --------------------------------------------------------------------------- #
# FastScanner — fenêtre de fraîcheur (le bug du PnL négatif)
# --------------------------------------------------------------------------- #
def _ws_msg(address, fills, channel=CHANNEL_SUBACCOUNTS):
    return SimpleNamespace(channel=channel, id=f"{address}/0", data={"fills": fills})


def test_scanner_keeps_fresh_drops_stale():
    captured = []
    sc = FastScanner(max_age_ms=4000, on_fresh_fill=captured.append)
    base = BASE_MS
    fresh = _raw_fill(id="fresh", createdAt="2026-06-12T00:00:00.000Z")
    stale = _raw_fill(id="stale", createdAt="2026-06-12T00:00:00.000Z")
    # now = base + 1s -> fresh OK ; un 2e fill avec age 8s -> rejeté
    out_fresh = sc.handle_ws_message(_ws_msg("0xabc", [fresh]), now_ms=base + 1000)
    out_stale = sc.handle_ws_message(_ws_msg("0xabc", [stale]), now_ms=base + 8000)
    assert [f.fill_id for f in out_fresh] == ["fresh"]
    assert out_stale == []  # 8 s > 4 s -> trop vieux, comme dans les logs
    assert [f.fill_id for f in captured] == ["fresh"]
    s = sc.stats()
    assert s["fills_fresh"] == 1
    assert s["fills_stale"] == 1


def test_scanner_dedupes_across_calls():
    sc = FastScanner(max_age_ms=10_000)
    base = BASE_MS
    msg = _ws_msg("0xabc", [_raw_fill(id="dup")])
    first = sc.handle_ws_message(msg, now_ms=base + 100)
    second = sc.handle_ws_message(msg, now_ms=base + 200)
    assert len(first) == 1
    assert second == []  # doublon ignoré
    assert sc.stats()["duplicates"] == 1


def test_scanner_ignores_other_channels():
    sc = FastScanner()
    msg = _ws_msg("0xabc", [_raw_fill()], channel="v4_trades")
    assert sc.handle_ws_message(msg, now_ms=BASE_MS) == []


def test_scanner_queue_and_drain():
    sc = FastScanner(max_age_ms=10_000)
    base = BASE_MS
    sc.handle_ws_message(
        _ws_msg("0xabc", [_raw_fill(id="a"), _raw_fill(id="b")]),
        now_ms=base + 100,
    )
    drained = sc.drain_fresh()
    assert sorted(f.fill_id for f in drained) == ["a", "b"]
    # File vidée
    assert sc.get_fresh(timeout_s=0.01) is None


# --------------------------------------------------------------------------- #
# Balayage REST injecté (testable hors réseau)
# --------------------------------------------------------------------------- #
def test_rest_fast_sweep_injected_fetch():
    sc = FastScanner(max_age_ms=10_000)
    base = BASE_MS

    def fake_fetch(addr):
        return {"fills": [_raw_fill(id=f"{addr}-1")]}

    out = sc.rest_fast_sweep(
        ["0xaaa", "0xbbb"], fetch_fn=fake_fetch, now_ms=base + 100
    )
    ids = sorted(f.fill_id for f in out)
    assert ids == ["0xaaa-1", "0xbbb-1"]
    assert all(f.source == "REST" for f in out)


def test_rest_sweep_handles_fetch_errors():
    sc = FastScanner(max_age_ms=10_000)

    def boom(addr):
        raise RuntimeError("réseau coupé")

    # Ne doit jamais lever: une source qui échoue == NO_TRADE silencieux
    assert sc.rest_fast_sweep(["0xaaa"], fetch_fn=boom) == []


# --------------------------------------------------------------------------- #
# Sécurité: aucune capacité d'ordre/signature
# --------------------------------------------------------------------------- #
def test_scanner_has_no_execution_methods():
    sc = FastScanner()
    forbidden = (
        "order", "sign", "submit", "send_order", "place",
        "withdraw", "deposit", "private_key", "mnemonic", "seed", "transfer",
    )
    names = [n for n in dir(sc) if not n.startswith("__")]
    for name in names:
        low = name.lower()
        assert not any(tok in low for tok in forbidden), f"méthode interdite: {name}"


def test_scanned_fill_freshness_helper():
    f = ScannedFill(
        address="0xabc", subaccount_number=0, market_id="BTC-USD", side="BUY",
        size=1.0, price=100.0, created_at_ms=0, fill_id="x", age_ms=3000,
    )
    assert f.is_fresh(4000) is True
    assert f.is_fresh(2000) is False
