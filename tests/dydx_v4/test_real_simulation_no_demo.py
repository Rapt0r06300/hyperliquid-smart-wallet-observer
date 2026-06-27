from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.config import load_config_from_env
from hyper_smart_observer.dydx_v4.wallet_discovery import DydxWalletDiscovery

ROOT = Path(__file__).resolve().parents[2]


def test_simulation_config_is_not_demo_by_default(monkeypatch):
    monkeypatch.delenv("DYDX_DEMO_MODE", raising=False)
    monkeypatch.delenv("DYDX_ALLOW_DEMO_FALLBACK", raising=False)
    cfg = load_config_from_env()
    assert cfg.demo_mode is False
    assert cfg.allow_demo_fallback is False
    assert cfg.paper_only is True
    assert cfg.read_only is True
    assert cfg.allow_trading is False
    assert cfg.allow_market_flow_solo_entries is False


def test_single_launcher_does_not_force_demo_mode():
    text = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="replace")
    assert 'DYDX_DEMO_MODE=1' not in text
    assert "DYDX_DEMO_MODE" not in text
    assert "DYDX_ALLOW_DEMO_FALLBACK" not in text
    assert "tools\\start_hypersmart_simulation.ps1" in text


def test_discovery_source_failure_returns_empty_real_result_not_demo():
    fake_cosmos = SimpleNamespace(scan_subaccounts=lambda **_kw: (_ for _ in ()).throw(RuntimeError("offline")))
    discovery = DydxWalletDiscovery(cosmos_client=fake_cosmos, rest_client=SimpleNamespace(), demo_mode=False)
    result = discovery.fast_discover(n=10)
    assert result.shortlisted == []
    assert result.discovery_method == "cosmos_lcd_unavailable"
    assert not hasattr(discovery, "_demo_mode")
    assert discovery._artificial_mode_requested is False


def test_discovery_empty_result_stays_empty_not_demo():
    fake_cosmos = SimpleNamespace(scan_subaccounts=lambda **_kw: [])
    discovery = DydxWalletDiscovery(cosmos_client=fake_cosmos, rest_client=SimpleNamespace(), demo_mode=False)
    result = discovery.fast_discover(n=10)
    assert result.shortlisted == []
    assert result.discovery_method == "fast_cosmos_lcd_empty"
    assert not hasattr(discovery, "_demo_mode")
    assert discovery._artificial_mode_requested is False


def test_async_discovery_source_failure_returns_empty_real_result_not_demo():
    fake_cosmos = SimpleNamespace(scan_subaccounts=lambda **_kw: (_ for _ in ()).throw(RuntimeError("offline")))
    discovery = DydxWalletDiscovery(cosmos_client=fake_cosmos, rest_client=SimpleNamespace(), demo_mode=False)
    result = asyncio.run(discovery.fast_discover_async(n=10))
    assert result.shortlisted == []
    assert result.discovery_method == "cosmos_lcd_async_unavailable"
    assert not hasattr(discovery, "_demo_mode")
    assert discovery._artificial_mode_requested is False


def test_simulation_v2_uses_smooth_real_tick_sampler_without_demo_label():
    text = (ROOT / "src" / "hl_observer" / "ui" / "static" / "simulation_v2.html").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "function recordVisualEquityPoint" in text
    assert "visual_mark_to_market" in text
    assert "VISUAL_POINT_MIN_MS=55" in text
    assert 'const REFRESH_MS=10000' in text
    assert 'const TICK_MIN_MS=350' in text
    assert 'const TICK_MAX_MS=900' in text
    assert '"/api/simulation/status?t="+Date.now()' in text
    assert "/api/simulation/overview" in text
    assert "function renderBotDetails" in text
    assert "function renderOverviewScanPanel" in text
    assert "overflow-anchor:none" in text
    assert "scrollbar-gutter:stable" in text
    assert "renderOverviewScanPanel(statusPayload,statusPayload.wallets||[])" in text
    assert "/api/dydx/realtime-tick" not in text
    assert "requestAnimationFrame(animateEquity)" in text



def test_launcher_keeps_public_market_flow_context_only():
    text = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="replace")
    assert "DYDX_ALLOW_MARKET_FLOW_SOLO" not in text
    assert "HYPERSMART_ALLOW_MARKET_FLOW_SOLO=0" in text
