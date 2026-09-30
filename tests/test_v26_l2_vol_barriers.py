"""V26 L2 — Tests des barrières SL/TP ajustées à la volatilité (hummingbot TripleBarrier).

100 % simulation : fixtures synthétiques (TEST_FIXTURE), aucun ordre réel, aucune I/O réseau.
"""

from __future__ import annotations

import pathlib

from hl_observer.paper_trading.sl_tp import SLTPConfig
from hl_observer.paper_trading.vol_adjusted_barriers import (
    MASTER_FLAG,
    MidVolEstimator,
    adjust_config,
    apply_sltp_exits_vol_adjusted,
    vol_factor_for_coin,
)

ENV_ON = {MASTER_FLAG: "1"}
ENV_OFF = {MASTER_FLAG: "0"}


# ---------------------------------------------------------------- adjust_config

def test_adjust_config_scales_all_barriers():
    base = SLTPConfig(stop_loss_bps=40.0, take_profit_bps=30.0, trailing_stop_bps=20.0, trailing_activation_bps=10.0)
    out = adjust_config(base, 2.0, sl_floor_bps=12.0)
    assert out.stop_loss_bps == 80.0
    assert out.take_profit_bps == 60.0
    assert out.trailing_stop_bps == 40.0
    assert out.trailing_activation_bps == 20.0
    assert out.breakeven_buffer_bps == base.breakeven_buffer_bps  # non scalé


def test_adjust_config_floor_protects_stop():
    base = SLTPConfig(stop_loss_bps=40.0, take_profit_bps=30.0)
    out = adjust_config(base, 0.5, sl_floor_bps=25.0)
    assert out.stop_loss_bps == 25.0  # 40*0.5=20 < plancher 25 -> plancher
    assert out.take_profit_bps == 15.0  # TP pas plancher


def test_adjust_config_none_trailing_stays_none():
    base = SLTPConfig(stop_loss_bps=40.0, take_profit_bps=30.0, trailing_stop_bps=None, trailing_activation_bps=None)
    out = adjust_config(base, 2.0, sl_floor_bps=1.0)
    assert out.trailing_stop_bps is None and out.trailing_activation_bps is None


# ---------------------------------------------------------------- estimateur & facteur

def test_estimator_needs_min_obs():
    est = MidVolEstimator()
    for i in range(3):
        est.record("BTC", 100.0 + i * 0.1, ts=1000.0 + i)
    assert est.range_bps("BTC", window_s=3600, min_obs=5, now=1010.0) is None
    assert vol_factor_for_coin("BTC", estimator=est, env={}, now=1010.0) == 1.0  # inconnu => neutre


def test_estimator_range_and_factor_clamps():
    est = MidVolEstimator()
    # range 100.0 -> 101.0 sur dernier 100.5 => ~99.5 bps ; ref 40 => facteur ~2.49
    for i, m in enumerate([100.0, 100.4, 101.0, 100.2, 100.5]):
        est.record("BTC", m, ts=1000.0 + i)
    rng = est.range_bps("BTC", window_s=3600, min_obs=5, now=1010.0)
    assert rng is not None and 98.0 < rng < 101.0
    f = vol_factor_for_coin("BTC", estimator=est, env={}, now=1010.0)
    assert 2.4 < f <= 2.5
    # clamp bas : marché quasi immobile
    est2 = MidVolEstimator()
    for i in range(6):
        est2.record("ETH", 100.0 + 0.0001 * i, ts=1000.0 + i)
    assert vol_factor_for_coin("ETH", estimator=est2, env={}, now=1010.0) == 0.5


def test_estimator_rejects_bad_values():
    est = MidVolEstimator()
    est.record("BTC", -5.0)
    est.record("BTC", float("nan"))
    est.record("", 100.0)
    assert est.range_bps("BTC", window_s=3600, min_obs=1) is None


# ---------------------------------------------------------------- wrapper drop-in

def _fixture(mark: float):
    positions = {"w1|BTC|LONG": {"size": 1.0, "avg_price": 100.0, "opened_at_ms": 1, "coin": "BTC"}}
    ledger: list[dict] = []
    marks = {"BTC": mark}
    return positions, ledger, marks


def _hot_estimator(now_s: float) -> MidVolEstimator:
    est = MidVolEstimator()
    for i, m in enumerate([100.0, 100.6, 101.2, 100.3, 100.8, 100.5]):  # range ~119 bps => facteur clampé 2.5
        est.record("BTC", m, ts=now_s - 10 + i)
    return est


def test_wrapper_flag_off_is_passthrough_identical():
    cfg = SLTPConfig(stop_loss_bps=40.0, take_profit_bps=300.0)
    # mark 99.40 = -60 bps => STOP_LOSS au config de base
    p1, l1, m1 = _fixture(99.40)
    closed_direct = apply_sltp_exits_vol_adjusted(p1, l1, m1, cost_bps=0.0, now_ms=2_000_000, config=cfg, env=ENV_OFF)
    assert len(closed_direct) == 1 and closed_direct[0]["reason"] == "STOP_LOSS"
    assert "vol_factor" not in closed_direct[0]  # passthrough pur
    assert p1 == {}  # position fermée/retirée


def test_wrapper_flag_on_wider_stop_survives():
    cfg = SLTPConfig(stop_loss_bps=40.0, take_profit_bps=300.0)
    now_ms = 2_000_000
    est = _hot_estimator(now_ms / 1000.0)
    p, l, m = _fixture(99.40)  # -60 bps : stop au base (40), PAS au SL ajusté (40*2.5=100)
    closed = apply_sltp_exits_vol_adjusted(
        p, l, m, cost_bps=0.0, now_ms=now_ms, config=cfg, env=ENV_ON, estimator=est
    )
    assert closed == []  # survit grâce au SL élargi par la vol
    assert "w1|BTC|LONG" in p  # position toujours ouverte


def test_wrapper_flag_on_still_stops_beyond_adjusted():
    cfg = SLTPConfig(stop_loss_bps=40.0, take_profit_bps=300.0)
    now_ms = 2_000_000
    est = _hot_estimator(now_ms / 1000.0)
    p, l, m = _fixture(98.50)  # -150 bps : au-delà même du SL ajusté (100 bps)
    closed = apply_sltp_exits_vol_adjusted(
        p, l, m, cost_bps=0.0, now_ms=now_ms, config=cfg, env=ENV_ON, estimator=est
    )
    assert len(closed) == 1 and closed[0]["reason"] == "STOP_LOSS"
    assert closed[0]["vol_adjusted"] is True and closed[0]["vol_factor"] == 2.5
    assert p == {}  # mutation répercutée sur le dict source
    # le ledger porte les barrières AJUSTÉES (traçabilité audit)
    assert l and abs(float(l[0]["sltp_stop_loss_bps"]) - 100.0) < 1e-6


def test_wrapper_low_vol_floor_via_env():
    cfg = SLTPConfig(stop_loss_bps=40.0, take_profit_bps=300.0)
    now_ms = 2_000_000
    est = MidVolEstimator()
    for i in range(6):  # marché immobile => facteur 0.5 => SL 20, mais plancher env 30
        est.record("BTC", 100.0, ts=now_ms / 1000.0 - 10 + i)
    env = {MASTER_FLAG: "1", "HYPERSMART_V26_SL_FLOOR_BPS": "30"}
    p, l, m = _fixture(99.75)  # -25 bps : sous le SL réduit (20) mais dans le plancher (30) => survit
    closed = apply_sltp_exits_vol_adjusted(
        p, l, m, cost_bps=0.0, now_ms=now_ms, config=cfg, env=env, estimator=est
    )
    assert closed == [] and "w1|BTC|LONG" in p


def test_wrapper_records_marks_even_flag_off():
    cfg = SLTPConfig(stop_loss_bps=400.0, take_profit_bps=500.0)
    est = MidVolEstimator()
    p, l, m = _fixture(100.0)
    apply_sltp_exits_vol_adjusted(p, l, m, cost_bps=0.0, now_ms=2_000_000, config=cfg, env=ENV_OFF, estimator=est)
    # l'estimateur a bien reçu le mark réel malgré flag OFF (observabilité)
    assert est.range_bps("BTC", window_s=3600, min_obs=1, now=2_000.0) is not None


# ---------------------------------------------------------------- sécurité

def test_no_real_trade_surface_in_l2_module():
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "hl_observer"
    text = (root / "paper_trading" / "vol_adjusted_barriers.py").read_text(encoding="utf-8")
    for forbidden in ("requests", "httpx", "aiohttp", "websocket", "/exchange", "private_key", "sign("):
        assert forbidden not in text, f"surface interdite: {forbidden}"
