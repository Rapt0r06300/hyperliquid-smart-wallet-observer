"""
Tests de l'integration scan rapide + flag de configuration.

100% deterministe, sans reseau. READ-ONLY / PAPER-ONLY.

Verifie: flag config defaut ON (fast scanner actif par defaut), activation par env,
suivi de shortlist, signal wallets qui viennent de bouger via un message WS
factice, stats, et absence de toute capacite d'ordre.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.config import DydxV4Config, load_config_from_env
from hyper_smart_observer.dydx_v4.fast_scan_integration import FastScanIntegration
from hyper_smart_observer.dydx_v4.wallet_discovery import DydxWalletDiscovery

A = "dydx1" + "a" * 39
B = "dydx1" + "b" * 39


# --------------------------------------------------------------------------- #
# Flag de configuration
# --------------------------------------------------------------------------- #
def test_config_flag_default_on():
    cfg = DydxV4Config()
    assert cfg.fast_scanner_enabled is True
    assert cfg.fast_scanner_hot_capacity == 1000


def test_config_flag_enabled_via_env(monkeypatch):
    monkeypatch.setenv("DYDX_FAST_SCANNER", "1")
    monkeypatch.setenv("DYDX_FAST_SCANNER_HOT_CAPACITY", "250")
    cfg = load_config_from_env()
    assert cfg.fast_scanner_enabled is True
    assert cfg.fast_scanner_hot_capacity == 250
    # La securite reste verrouillee meme flag active
    assert cfg.read_only is True and cfg.paper_only is True
    assert cfg.allow_trading is False


def test_config_flag_on_by_default_via_env(monkeypatch):
    monkeypatch.delenv("DYDX_FAST_SCANNER", raising=False)
    cfg = load_config_from_env()
    assert cfg.fast_scanner_enabled is True


# --------------------------------------------------------------------------- #
# Integration
# --------------------------------------------------------------------------- #
def _fresh_ws_msg(address):
    now_iso = datetime.now(timezone.utc).isoformat()
    fill = {
        "id": f"{address}-fill-1",
        "market": "BTC-USD",
        "side": "BUY",
        "size": "0.5",
        "price": "60000",
        "createdAt": now_iso,
    }
    return SimpleNamespace(channel="v4_subaccounts", id=f"{address}/0", data={"fills": [fill]})


def test_integration_constructs_without_network():
    integ = FastScanIntegration(ws_client=None)
    assert integ.scanner is not None
    assert integ.harvester is not None
    s = integ.stats()
    assert s["read_only"] is True and s["paper_only"] is True
    assert s["ws_attached"] is False


def test_integration_track_shortlist():
    integ = FastScanIntegration(ws_client=None, hot_capacity=10)
    shortlist = [
        SimpleNamespace(address=A, total_score=80.0),
        SimpleNamespace(address=B, total_score=60.0),
        SimpleNamespace(address=None, total_score=10.0),  # ignore
    ]
    n = integ.track_shortlist(shortlist)
    assert n == 2
    assert A in integ.scanner.hot.active()
    assert B in integ.scanner.hot.active()


def test_integration_detects_moved_wallets():
    integ = FastScanIntegration(ws_client=None, max_age_ms=600_000)  # fenetre large
    integ.note_ws_message(_fresh_ws_msg(A))
    moved = integ.wallets_that_just_moved()
    assert A in moved
    # Draine: un 2e appel sans nouveau message ne renvoie rien
    assert integ.wallets_that_just_moved() == set()


def test_integration_ws_hook_attached():
    fake_ws = SimpleNamespace(_on_message_cb=None)
    integ = FastScanIntegration(ws_client=fake_ws)
    # Le hook pointe vers le scanner via l'integration
    assert fake_ws._on_message_cb == integ.note_ws_message
    assert integ.stats()["ws_attached"] is True


def test_integration_has_no_execution_methods():
    integ = FastScanIntegration(ws_client=None)
    forbidden = ("order", "sign", "submit", "place", "withdraw", "deposit",
                 "private_key", "mnemonic", "transfer", "buy", "sell")
    for name in [n for n in dir(integ) if not n.startswith("__")]:
        low = name.lower()
        assert not any(tok in low for tok in forbidden), f"methode interdite: {name}"


# --------------------------------------------------------------------------- #
# Decouverte on-chain Cosmos
# --------------------------------------------------------------------------- #
def test_integration_cosmos_discovery_end_to_end():
    fake = SimpleNamespace()
    fake.scan_subaccounts = lambda **kw: [
        SimpleNamespace(address=A, usdc_balance=50_000.0),
        SimpleNamespace(address=B, usdc_balance=20_000.0),
    ]
    integ = FastScanIntegration(ws_client=None, hot_capacity=10)
    integ.enable_cosmos_discovery(fake)
    integ.enable_cosmos_discovery(fake)  # idempotent -> une seule source
    new = integ.refresh_discovery()
    assert new == 2
    assert A in integ.scanner.hot.active()
    assert integ.stats()["harvested_addresses"] == 2


def test_wallet_discovery_async_scores_500_wallets_under_3s_without_network():
    fake_cosmos = SimpleNamespace()

    def _scan_subaccounts(**_kw):
        return [
            SimpleNamespace(
                address=f"dydx1{i:039d}",
                subaccount_number=0,
                usdc_balance=10_000.0 + i,
                positions=[
                    SimpleNamespace(market_id="ETH-USD", side="LONG", size=1.0)
                ],
                total_position_count=1,
            )
            for i in range(500)
        ]

    fake_cosmos.scan_subaccounts = _scan_subaccounts
    fake_rest = SimpleNamespace(paginate_fills=lambda **_kw: [])
    discovery = DydxWalletDiscovery(
        cosmos_client=fake_cosmos,
        rest_client=fake_rest,
        demo_mode=False,
    )

    started = time.perf_counter()
    result = asyncio.run(
        discovery.fast_discover_async(n=50, max_candidates=500, concurrency=10)
    )
    elapsed = time.perf_counter() - started

    assert result.discovery_method == "fast_cosmos_lcd_async"
    assert result.candidates_scanned == 500
    assert len(result.shortlisted) == 50
    assert elapsed < 3.0
    assert all(w.total_score > 0 for w in result.shortlisted)
