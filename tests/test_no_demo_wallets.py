from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def test_dydx_legacy_demo_flags_are_ignored(monkeypatch) -> None:
    from hyper_smart_observer.dydx_v4.config import load_config_from_env

    monkeypatch.setenv("DYDX_DEMO_MODE", "1")
    monkeypatch.setenv("DYDX_ALLOW_DEMO_FALLBACK", "1")
    cfg = load_config_from_env()

    assert cfg.demo_mode is False
    assert cfg.allow_demo_fallback is False
    assert cfg.paper_only is True
    assert cfg.read_only is True
    assert cfg.allow_trading is False


def test_demo_wallet_builder_is_not_importable() -> None:
    import hyper_smart_observer.dydx_v4.wallet_discovery as discovery

    assert not hasattr(discovery, "_build_demo_wallets")


def test_discovery_never_invents_wallets_when_demo_requested() -> None:
    from hyper_smart_observer.dydx_v4.wallet_discovery import DydxWalletDiscovery

    fake_cosmos = SimpleNamespace(scan_subaccounts=lambda **_kw: [])
    discovery = DydxWalletDiscovery(
        cosmos_client=fake_cosmos,
        rest_client=SimpleNamespace(),
        demo_mode=True,
    )

    result = discovery.fast_discover(n=10)

    assert result.shortlisted == []
    assert result.candidates_scanned == 0
    assert result.discovery_method == "artificial_generation_disabled"


def test_runtime_has_no_demo_wallet_runtime_paths() -> None:
    forbidden = ("demo_synthetic", "_build_demo_wallets", "_demo_mode")
    files = [
        path
        for base in (ROOT / "hyper_smart_observer", ROOT / "src")
        for path in base.rglob("*.py")
        if "__pycache__" not in path.parts
    ]

    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for needle in forbidden:
            if needle.lower() in text:
                offenders.append(f"{path.relative_to(ROOT)}::{needle}")

    assert offenders == []
