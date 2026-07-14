"""Tests sécurité & résilience — renforcent le no-real-trade."""
from __future__ import annotations

import pytest

from hl_observer.backtesting.safety_tools import (
    chaos_wrap,
    deterministic_replay,
    kill_switch_engaged,
    no_real_trade_violations,
    scan_for_secrets,
)


def test_scan_for_secrets_flags_private_key():
    bad = "priv = 0x" + "a" * 64
    assert scan_for_secrets(bad)
    assert scan_for_secrets("rien de sensible ici") == []


def test_no_real_trade_violations_fuzz():
    safe = {"REAL_MAINNET_TRADING": "false", "TESTNET_ONLY": "true"}
    assert no_real_trade_violations(safe) == []
    danger = {"REAL_MAINNET_TRADING": "true", "TESTNET_ONLY": "false", "ENABLE_REAL_ORDERS": "1"}
    v = no_real_trade_violations(danger)
    assert "REAL_MAINNET_TRADING_ENABLED" in v
    assert "TESTNET_ONLY_DISABLED" in v
    assert "REAL_ORDERS_ENABLED" in v


def test_kill_switch(tmp_path):
    p = str(tmp_path / "STOP")
    assert kill_switch_engaged(p) is False
    open(p, "w").close()
    assert kill_switch_engaged(p) is True


def test_chaos_injects_deterministic_failures():
    f = chaos_wrap(lambda: "ok", failure_rate=1.0, seed=1)
    with pytest.raises(RuntimeError):
        f()
    g = chaos_wrap(lambda: "ok", failure_rate=0.0, seed=1)
    assert g() == "ok"


def test_deterministic_replay_is_reproducible():
    events = [{"add": 1}, {"add": 2}, {"add": 3}]

    def handler(state, e):
        s = dict(state)
        s["total"] = s.get("total", 0) + e["add"]
        return s

    a = deterministic_replay(events, handler)
    b = deterministic_replay(events, handler)
    assert a == b == {"total": 6}
