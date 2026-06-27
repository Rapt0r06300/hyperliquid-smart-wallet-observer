"""Phase 2 (live): volatility_context computed from candleSnapshot inside the
decision-path feature builder `_market_features_by_coin`.

- candles present  -> volatility populated (realized vol available);
- candles empty    -> degraded (no realized vol), never fabricated;
- no candle method -> volatility_context None (degraded);
- extreme candles  -> higher realized vol than calm (real signal, not invented).

Robust to volatility_context being a VolatilityContext object or a float.
No network, deterministic.
"""

from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_loop import _market_features_by_coin
from tests.hl_runtime_fakes import RuntimeFakeInfoClient, healthy_l2


def _candle_series(amp: float, n: int = 20, base: float = 50_000.0) -> list[dict]:
    out = []
    for i in range(n):
        c = base * (1 + amp * (1 if i % 2 else -1))
        out.append({"t": i, "c": str(c), "h": str(c * (1 + amp)), "l": str(c * (1 - amp))})
    return out


def _realized(feature):
    v = feature.volatility_context
    if v is None:
        return None
    return getattr(v, "realized_vol_bps", v)


def _features(fake):
    return _market_features_by_coin(
        info_client=fake, all_mids={"BTC": "50000.0"}, coins=["BTC"],
        l2_cache={}, candle_cache={}, source_failures=[],
    )


def test_volatility_present_when_candles_available():
    fake = RuntimeFakeInfoClient(l2_book=healthy_l2(), candles=_candle_series(0.001))
    feats = _features(fake)
    assert "candleSnapshot" in fake.calls
    assert _realized(feats["BTC"]) is not None


def test_volatility_degraded_when_candles_empty():
    feats = _features(RuntimeFakeInfoClient(l2_book=healthy_l2(), candles=[]))
    assert _realized(feats["BTC"]) is None


def test_volatility_none_when_no_candle_method():
    fake = RuntimeFakeInfoClient(l2_book=healthy_l2())
    fake.get_candle_snapshot = None
    feats = _features(fake)
    assert feats["BTC"].volatility_context is None


def test_extreme_volatility_is_higher_not_fabricated():
    calm = _realized(_features(RuntimeFakeInfoClient(l2_book=healthy_l2(), candles=_candle_series(0.0005)))["BTC"])
    wild = _realized(_features(RuntimeFakeInfoClient(l2_book=healthy_l2(), candles=_candle_series(0.05)))["BTC"])
    assert calm is not None and wild is not None
    assert wild > calm
