"""Famille C #10 : sizing ciblé-volatilité (causal).

La taille est mise à l'échelle par cible / volatilité réalisée causale récente
(carnets ts <= signal), bornée [0.5, 1.5] : plus petite en forte vol, plus grande
en vol calme. Homogénéise le PnL quotidien -> σ plus bas -> LCB resserré.
Param optionnel `vol_target_move_frac` (0.0 = désactivé, rétro-compatible).
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting import copy_vault_v21_frozen as V21


def _book(ts_ms: int, mid: float, spread: float = 0.2) -> dict:
    return {
        "ts_ms": ts_ms,
        "bid": mid - spread / 2.0,
        "ask": mid + spread / 2.0,
        "causal_observation": True,
    }


def _capture_execute(calls: list[float]):
    def execute(metaorder, _books, *, notional_usd, **_kwargs):
        signal_ms = int(metaorder["signal_ts_ms"])
        calls.append(notional_usd)
        return (
            {
                "entry_ts_ms": signal_ms + 1,
                "exit_ts_ms": signal_ms + 100,
                "direction": 1,
                "quantity": 1.0,
                "entry_price": 100.0,
                "notional_usd": notional_usd,
                "net_pnl_usd": 0.0,
            },
            "LIQUIDATABLE_NET",
        )
    return execute


def _candidate() -> list[dict]:
    return [{
        "signal_ts_ms": 2_000,
        "metaorder_id": "m0",
        "vault": "v0",
        "coin": "BTC",
        "direction": 1,
        "signed_reference_depth_imbalance": 0.2,
        "reference_two_sided_capacity_usd": 10_000.0,
    }]


def _params(*, vol_target_move_frac: float | None) -> dict:
    params = {
        "horizon_ms": 300_000,
        "vault_daily_limit": 10,
        "coin_daily_limit": 10,
        "max_open_positions": 10,
        "daily_profit_lock_usd": 1_000.0,
        "core_notional_usd": 50.0,
        "probe_notional_usd": 20.0,
        "stop_loss_bps": 50.0,
        "take_profit_bps": 100.0,
    }
    if vol_target_move_frac is not None:
        params["vol_target_move_frac"] = vol_target_move_frac
    return params


def test_high_volatility_shrinks_size_to_lower_clamp(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []
    monkeypatch.setattr(V21.cv, "execute_metaorder", _capture_execute(calls))
    # Mid ~±1% -> vol réalisée ~0.01 >> cible 0.002 -> scale 0.2 borné à 0.5.
    mids = [100.0, 101.0, 100.0, 101.0, 100.0, 101.0]
    books = {"BTC": [_book(1_000 + i * 100, m) for i, m in enumerate(mids)]}
    V21._settle(_candidate(), books, segment="train", params=_params(vol_target_move_frac=0.002))
    assert calls[0] == pytest.approx(0.5 * 50.0)  # 25.0 (trade réel ; placebo identique)


def test_low_volatility_grows_size_to_upper_clamp(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []
    monkeypatch.setattr(V21.cv, "execute_metaorder", _capture_execute(calls))
    # Mid quasi plat -> vol réalisée minuscule << cible -> scale borné à 1.5.
    mids = [100.0, 100.001, 100.0, 100.001, 100.0, 100.001]
    books = {"BTC": [_book(1_000 + i * 100, m) for i, m in enumerate(mids)]}
    V21._settle(_candidate(), books, segment="train", params=_params(vol_target_move_frac=0.002))
    assert calls[0] == pytest.approx(1.5 * 50.0)  # 75.0


def test_disabled_vol_target_leaves_size_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []
    monkeypatch.setattr(V21.cv, "execute_metaorder", _capture_execute(calls))
    mids = [100.0, 101.0, 100.0, 101.0, 100.0, 101.0]
    books = {"BTC": [_book(1_000 + i * 100, m) for i, m in enumerate(mids)]}
    # 0.0 = désactivé -> taille cœur inchangée.
    V21._settle(_candidate(), books, segment="train", params=_params(vol_target_move_frac=0.0))
    assert calls[0] == 50.0
    # Param absent -> rétro-compatible, inchangé.
    calls.clear()
    V21._settle(_candidate(), books, segment="train", params=_params(vol_target_move_frac=None))
    assert calls[0] == 50.0


def test_vol_target_needs_causal_history_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []
    monkeypatch.setattr(V21.cv, "execute_metaorder", _capture_execute(calls))
    # Carnets APRÈS le signal : ignorés (aucun look-ahead) -> pas assez d'historique
    # causal -> aucune mise à l'échelle -> taille cœur.
    mids = [100.0, 101.0, 100.0, 101.0, 100.0, 101.0]
    books = {"BTC": [_book(5_000 + i * 100, m) for i, m in enumerate(mids)]}  # tous > signal 2_000
    V21._settle(_candidate(), books, segment="train", params=_params(vol_target_move_frac=0.002))
    assert calls[0] == 50.0
