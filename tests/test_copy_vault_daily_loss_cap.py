"""Famille C #9 : plafond de perte journalière.

Miroir risque de daily_profit_lock : une fois -X USD réalisés dans la journée,
le labo cesse d'ouvrir de nouvelles positions ce jour-là. Causal (ne compte que
les trades déjà clôturés au signal), écrête les pires jours -> réduit σ ->
resserre le LCB. Param optionnel : absent => aucun plafond (rétro-compatible).
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting import copy_vault_v21_frozen as V21


def _losing_execute(_metaorder, _books, *, notional_usd, **_kwargs):
    signal_ms = int(_metaorder["signal_ts_ms"])
    return (
        {
            "entry_ts_ms": signal_ms + 1,
            "exit_ts_ms": signal_ms + 100,
            "direction": 1,
            "quantity": 1.0,
            "entry_price": 100.0,
            "notional_usd": notional_usd,
            "net_pnl_usd": -0.12 * float(notional_usd),
        },
        "LIQUIDATABLE_NET",
    )


def _candidates(count: int) -> list[dict]:
    # Signaux le même jour UTC, chacun après la clôture du précédent (+100 ms).
    return [
        {
            "signal_ts_ms": 1_000 + index * 1_000,
            "metaorder_id": f"meta-{index}",
            "vault": f"vault-{index}",
            "coin": "BTC",
            "direction": 1,
            "signed_reference_depth_imbalance": 0.2,
            "reference_two_sided_capacity_usd": 10_000.0,
        }
        for index in range(count)
    ]


def _params(*, daily_loss_cap_usd: float | None) -> dict:
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
    if daily_loss_cap_usd is not None:
        params["daily_loss_cap_usd"] = daily_loss_cap_usd
    return params


def test_daily_loss_cap_stops_opening_after_cap_is_breached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(V21.cv, "execute_metaorder", _losing_execute)
    trades, _placebos, audit = V21._settle(
        _candidates(4), {"BTC": []}, segment="train",
        params=_params(daily_loss_cap_usd=5.0),
    )
    # 1er trade exécuté (perte -6). Dès le 2e signal, realized_today=-6 <= -5 => stop.
    assert len(trades) == 1
    assert audit["DAILY_LOSS_CAP_REJECTED"] == 3


def test_no_cap_lets_all_losing_trades_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(V21.cv, "execute_metaorder", _losing_execute)
    # Sans plafond (param absent) : comportement historique inchangé.
    trades, _placebos, audit = V21._settle(
        _candidates(4), {"BTC": []}, segment="train",
        params=_params(daily_loss_cap_usd=None),
    )
    assert len(trades) == 4
    assert audit.get("DAILY_LOSS_CAP_REJECTED", 0) == 0


def test_cap_scales_with_capital_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(V21.cv, "execute_metaorder", _losing_execute)
    # Scénario de capacité x2 : le plafond est mis à l'échelle comme le sizing.
    trades, _placebos, audit = V21._settle(
        _candidates(4), {"BTC": []}, segment="capacity_700",
        params=_params(daily_loss_cap_usd=5.0),
        capital_scenario_usd=2 * V21.PAPER_EQUITY_USD,
    )
    # Plafond mis à l'échelle = 10 ; pertes -12 chacune (notional x2) -> stop après le 1er.
    assert len(trades) == 1
    assert audit["DAILY_LOSS_CAP_REJECTED"] == 3
