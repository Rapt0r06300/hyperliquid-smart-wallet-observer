"""A1 — contrat du gate composite pré-trade (DATA-1 + RISK-1 + MARKET-1/2 + régime).

Prouve: deny-by-default (tous flags OFF = neutre, autorise) ; chaque flag ON
applique son sous-gate ; donnée douteuse -> NO_TRADE avec raison ; JAMAIS
d'exécution réelle. Chaque sous-brique est activable indépendamment (A/B).
"""

from __future__ import annotations

from hl_observer.integration.risk_quality_gate import evaluate_pre_trade

_FLAGS = [
    "HYPERSMART_GATE_DATA_QUALITY",
    "HYPERSMART_GATE_REGIME_VOLUME",
    "HYPERSMART_GATE_MARKET_CLASS",
    "HYPERSMART_GATE_CALENDAR",
    "HYPERSMART_GATE_CORRELATION",
]


def _base():
    return dict(
        coin="HYPE", side="LONG", raw_edge_bps=50.0, notional_usdt=100.0,
        open_positions=[],
        market={"l2_depth_usdt": 500_000.0, "daily_volume_usdt": 5e7, "regime": "trending", "volume_zscore": 1.0},
        data={"price": 100.0, "recent_prices": [99.0, 100.0, 101.0],
              "prices_by_source": {"hl": 100.0, "px": 100.1}, "last_update_ms": 1_000, "now_ms": 3_000},
        calendar={"utc_weekday": 2, "utc_hour": 14, "now_ms": 3_000, "macro_events_ms": []},
    )


def _clear(mp):
    for f in _FLAGS:
        mp.delenv(f, raising=False)


def test_deny_by_default_all_off_is_neutral_allow(monkeypatch):
    _clear(monkeypatch)
    r = evaluate_pre_trade(**_base())
    assert r["allowed"] is True and r["verdict"] == "OPEN_ALLOWED"
    assert r["gates_applied"] == []                 # aucun gate actif par défaut
    assert r["real_execution"] is False and r["paper_only"] is True


def test_data_quality_gate_blocks_fat_finger(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HYPERSMART_GATE_DATA_QUALITY", "1")
    bad = _base()
    bad["data"] = dict(bad["data"], price=200.0)     # +100% vs médiane 100 = fat-finger
    r = evaluate_pre_trade(**bad)
    assert r["allowed"] is False and r["verdict"] == "NO_TRADE"
    assert "PRICE_OUTLIER_FAT_FINGER" in r["reasons"]


def test_each_flag_is_consumed_and_applied(monkeypatch):
    # chaque flag ON => son sous-gate apparaît dans gates_applied (preuve de câblage)
    for flag, marker in [
        ("HYPERSMART_GATE_DATA_QUALITY", "DATA_QUALITY"),
        ("HYPERSMART_GATE_REGIME_VOLUME", "REGIME_VOLUME"),
        ("HYPERSMART_GATE_MARKET_CLASS", "MARKET_CLASS"),
        ("HYPERSMART_GATE_CALENDAR", "CALENDAR"),
        ("HYPERSMART_GATE_CORRELATION", "CORRELATION"),
    ]:
        _clear(monkeypatch)
        monkeypatch.setenv(flag, "1")
        r = evaluate_pre_trade(**_base())
        assert any(g.startswith(marker) for g in r["gates_applied"]), (flag, r["gates_applied"])
        assert r["real_execution"] is False


def test_never_real_execution_even_with_all_gates(monkeypatch):
    _clear(monkeypatch)
    for f in _FLAGS:
        monkeypatch.setenv(f, "1")
    r = evaluate_pre_trade(**_base())
    assert r["real_execution"] is False and r["paper_only"] is True
