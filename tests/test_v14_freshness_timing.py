"""V14 #166-#170 — freshness audit, liquidation signal, clock offset, whale-primary
gate, warmup guard, and the top-level log purge. Pure / paper-only / read-only."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# #166 freshness_audit
# ---------------------------------------------------------------------------
from hl_observer.realtime.freshness_audit import (
    build_age_histogram,
    build_stage_latency,
    build_freshness_audit,
    build_freshness_audit_from_events,
    format_freshness_audit,
)


def test_age_histogram_buckets_and_ratios():
    ages = [500, 900, 1500, 3000, 9000, 40000]  # ms
    h = build_age_histogram(ages, stale_threshold_ms=15000)
    assert h.total == 6
    # two ages <= 1000ms (ultra-hot)
    assert h.fresh_count == 2
    assert h.buckets[0].label == "<=1000ms" and h.buckets[0].count == 2
    # one age > 30000ms in the overflow bucket
    assert h.buckets[-1].count == 1
    # one age (40000) is > stale threshold 15000
    assert h.stale_count == 1
    assert 0.0 < h.stale_ratio < 0.2


def test_stage_latency_percentiles():
    st = build_stage_latency("capture", [100, 200, 300, 400, 500])
    assert st.samples == 5
    assert st.min_ms == 100 and st.max_ms == 500
    assert st.avg_ms == 300
    assert st.p50_ms == 300


def test_freshness_audit_status_and_no_data():
    fresh = build_freshness_audit(total_age_ms=[200, 500, 800])
    assert fresh.status == "OK"
    stale = build_freshness_audit(total_age_ms=[20000, 30000, 40000], stale_threshold_ms=15000)
    assert stale.status == "MOSTLY_STALE"
    empty = build_freshness_audit(total_age_ms=[])
    assert empty.status == "NO_SIGNAL_AGE_DATA"
    assert "freshness_audit" in format_freshness_audit(fresh)


@dataclass
class _Ev:
    exchange_ts_ms: float | None = None
    recv_ts_ms: float | None = None
    decision_ts_ms: float | None = None
    signal_age_ms: float | None = None


def test_freshness_audit_from_events_stages():
    events = [
        _Ev(exchange_ts_ms=1000, recv_ts_ms=1300, decision_ts_ms=1500, signal_age_ms=500),
        _Ev(exchange_ts_ms=2000, recv_ts_ms=2200, decision_ts_ms=2600, signal_age_ms=600),
    ]
    audit = build_freshness_audit_from_events(events)
    names = {s.name for s in audit.stages}
    assert "capture_exchange_to_recv" in names
    assert "compute_recv_to_decision" in names
    assert "total" in names
    cap = next(s for s in audit.stages if s.name == "capture_exchange_to_recv")
    assert cap.samples == 2  # (1300-1000)=300, (2200-2000)=200


# ---------------------------------------------------------------------------
# #167 liquidation_signal
# ---------------------------------------------------------------------------
from hl_observer.signals.liquidation_signal import (
    LiquidationConfig,
    LiquidationEvent,
    build_liquidation_signal,
)


def _liqs(coin, side, n, each, now, step=1000):
    return [LiquidationEvent(coin=coin, liquidated_side=side, notional_usdc=each, ts_ms=now - i * step) for i in range(n)]


def test_liquidation_fresh_cascade_reversion_and_momentum():
    now = 1_000_000
    events = _liqs("BTC", "LONG", 4, 20_000, now)  # 80k, longs liquidated -> flush down
    sig = build_liquidation_signal(events, now_ms=now, coin="BTC", config=LiquidationConfig(mode="reversion"))
    assert sig is not None
    assert sig.is_fresh_trigger is True
    assert sig.dominant_liquidated_side == "LONG"
    assert sig.momentum_side == "SHORT" and sig.reversion_side == "LONG"
    assert sig.trigger_side == "LONG"          # reversion = bounce
    assert 0.0 < sig.strength <= 1.0
    sig_m = build_liquidation_signal(events, now_ms=now, coin="BTC", config=LiquidationConfig(mode="momentum"))
    assert sig_m.trigger_side == "SHORT"       # momentum = continuation


def test_liquidation_too_small_not_fresh_and_filters():
    now = 1_000_000
    small = _liqs("BTC", "SHORT", 2, 1_000, now)  # 2k, count 2 -> below thresholds
    sig = build_liquidation_signal(small, now_ms=now, coin="BTC")
    assert sig is not None and sig.is_fresh_trigger is False
    # wrong coin -> None
    assert build_liquidation_signal(small, now_ms=now, coin="ETH") is None
    # all stale (older than window) -> None
    old = _liqs("BTC", "LONG", 4, 20_000, now - 200_000)
    assert build_liquidation_signal(old, now_ms=now, coin="BTC") is None


def test_liquidation_short_squeeze_sides():
    now = 1_000_000
    events = _liqs("ETH", "SHORT", 5, 30_000, now)  # shorts liquidated -> squeeze up
    sig = build_liquidation_signal(events, now_ms=now, coin="ETH", config=LiquidationConfig(mode="reversion"))
    assert sig.dominant_liquidated_side == "SHORT"
    assert sig.momentum_side == "LONG" and sig.reversion_side == "SHORT"
    assert sig.read_only is True and sig.execution == "forbidden"


# ---------------------------------------------------------------------------
# #169 clock_offset
# ---------------------------------------------------------------------------
from hl_observer.realtime.clock_offset import (
    ClockSample,
    corrected_signal_age_ms,
    estimate_clock_offset,
    estimate_offset_one_way,
)


def test_clock_offset_ntp_estimate_and_correction():
    # Server clock is +1000ms ahead of local; symmetric 200ms round trip.
    samples = [
        ClockSample(t0_local_send_ms=0, t_server_ms=1100, t1_local_recv_ms=200),
        ClockSample(t0_local_send_ms=10, t_server_ms=1110, t1_local_recv_ms=210),
    ]
    est = estimate_clock_offset(samples)
    assert est.method == "ntp" and est.trusted is True
    assert abs(est.offset_ms - 1000.0) < 1e-6
    # raw age would be 1000ms; correction makes it 2000ms (more stale = conservative).
    age = corrected_signal_age_ms(local_now_ms=5000, server_event_ms=4000, estimate=est)
    assert abs(age - 2000.0) < 1e-6


def test_clock_offset_one_way_is_untrusted_and_not_applied():
    pairs = [(4000.0, 3100.0), (4000.0, 3050.0)]  # local_recv - server_send = -900, -950
    est = estimate_offset_one_way(pairs)
    assert est.method == "one_way_lower_bound" and est.trusted is False
    # untrusted estimate must NOT inflate freshness: correction falls back to raw age.
    age = corrected_signal_age_ms(local_now_ms=5000, server_event_ms=4000, estimate=est)
    assert abs(age - 1000.0) < 1e-6
    # empty -> none
    assert estimate_clock_offset([]).method == "none"


def test_corrected_age_clamps_non_negative():
    age = corrected_signal_age_ms(local_now_ms=1000, server_event_ms=5000, estimate=None)
    assert age == 0.0


# ---------------------------------------------------------------------------
# #168 whale_primary_gate
# ---------------------------------------------------------------------------
from hl_observer.signals.whale_primary_gate import (
    ACCEPT_MARKER,
    REJECT_REASON as WHALE_REJECT,
    apply_whale_primary_promotion,
)


def test_whale_primary_promotion_only_reduces():
    # authoritative + accepting + KNOWN no-primary -> reject
    assert apply_whale_primary_promotion(score_reason=ACCEPT_MARKER, whale_primary=False, authoritative=True) == WHALE_REJECT
    # unknown (None) never blocks
    assert apply_whale_primary_promotion(score_reason=ACCEPT_MARKER, whale_primary=None, authoritative=True) == ACCEPT_MARKER
    # primary present -> unchanged
    assert apply_whale_primary_promotion(score_reason=ACCEPT_MARKER, whale_primary=True, authoritative=True) == ACCEPT_MARKER
    # shadow (authoritative False) -> no-op even when no primary
    assert apply_whale_primary_promotion(score_reason=ACCEPT_MARKER, whale_primary=False, authoritative=False) == ACCEPT_MARKER
    # never flips an existing reject into an accept
    assert apply_whale_primary_promotion(score_reason="REJECT_EDGE_NEGATIVE", whale_primary=True, authoritative=True) == "REJECT_EDGE_NEGATIVE"


# ---------------------------------------------------------------------------
# #170 warmup_guard
# ---------------------------------------------------------------------------
from hl_observer.signals.warmup_guard import (
    WarmupConfig,
    apply_warmup_promotion,
    warmup_status,
    REJECT_REASON as WARMUP_REJECT,
)


def test_warmup_status_ready_and_missing():
    ready = warmup_status(bars_by_tf={"1m": 300, "5m": 300, "15m": 300, "1h": 300}, features_ready=True)
    assert ready.ready is True and ready.reason == "READY"
    not_ready = warmup_status(bars_by_tf={"1m": 50, "5m": 300, "15m": 300, "1h": 300}, features_ready=True)
    assert not_ready.ready is False
    assert any(m.startswith("1m:") for m in not_ready.missing)
    # missing features blocks too
    no_feat = warmup_status(bars_by_tf={"1m": 300, "5m": 300, "15m": 300, "1h": 300}, features_ready=False)
    assert no_feat.ready is False


def test_warmup_promotion_only_reduces():
    assert apply_warmup_promotion(score_reason=ACCEPT_MARKER, warmup_ready=False, authoritative=True) == WARMUP_REJECT
    assert apply_warmup_promotion(score_reason=ACCEPT_MARKER, warmup_ready=None, authoritative=True) == ACCEPT_MARKER
    assert apply_warmup_promotion(score_reason=ACCEPT_MARKER, warmup_ready=True, authoritative=True) == ACCEPT_MARKER
    assert apply_warmup_promotion(score_reason=ACCEPT_MARKER, warmup_ready=False, authoritative=False) == ACCEPT_MARKER


# ---------------------------------------------------------------------------
# log purge — top-level reset that protects AI intelligence
# ---------------------------------------------------------------------------
from hl_observer.runtime.session_logs import (
    MOJIBAKE_LOGS_TO_SEND_DIRNAME,
    CANONICAL_LOGS_TO_SEND_DIRNAME,
    purge_stale_top_level_logs,
    format_purged_logs,
)


def _make_logs_tree(root: Path) -> None:
    logs = root / "logs"
    logs.mkdir(parents=True)
    (logs / "hypersmart_simulation_live.log").write_text("X" * 5000, encoding="utf-8")
    (logs / "hypersmart_poller_stdout.log").write_text("Y" * 3000, encoding="utf-8")
    (logs / "logs à envoyer.zip").write_bytes(b"Z" * 4000)
    (logs / "hl_observer.sqlite3").write_bytes(b"D" * 2000)         # DB -> must be preserved
    (logs / "hypersmart_poll_loop.lock").write_text("", encoding="utf-8")
    moji = logs / MOJIBAKE_LOGS_TO_SEND_DIRNAME
    moji.mkdir()
    (moji / "old.json").write_text("{}", encoding="utf-8")
    bundle = logs / CANONICAL_LOGS_TO_SEND_DIRNAME
    bundle.mkdir()
    (bundle / "hypersmart_ia_train.log").write_text("ai-trace", encoding="utf-8")
    # AI intelligence lives OUTSIDE logs/, under runtime/ -> must never be touched.
    rt = root / "runtime" / "ml"
    rt.mkdir(parents=True)
    (rt / "training_samples.jsonl").write_text('{"x":1}\n', encoding="utf-8")
    (root / "runtime" / "models").mkdir(parents=True)
    (root / "runtime" / "models" / "trade_model_v13.json").write_text('{"w":[0.1]}', encoding="utf-8")


def test_purge_resets_logs_but_preserves_ai_and_db(tmp_path):
    _make_logs_tree(tmp_path)
    res = purge_stale_top_level_logs(tmp_path)
    logs = tmp_path / "logs"
    # rolling .log truncated to 0 bytes (file kept)
    live = logs / "hypersmart_simulation_live.log"
    assert live.exists() and live.stat().st_size == 0
    # heavy zip deleted
    assert not (logs / "logs à envoyer.zip").exists()
    # mojibake dir removed
    assert not (logs / MOJIBAKE_LOGS_TO_SEND_DIRNAME).exists()
    # DB preserved
    assert (logs / "hl_observer.sqlite3").exists() and (logs / "hl_observer.sqlite3").stat().st_size == 2000
    # canonical evidence bundle + its AI trace preserved (subdir untouched)
    assert (logs / CANONICAL_LOGS_TO_SEND_DIRNAME / "hypersmart_ia_train.log").read_text(encoding="utf-8") == "ai-trace"
    # AI intelligence under runtime/ untouched
    assert (tmp_path / "runtime" / "ml" / "training_samples.jsonl").read_text(encoding="utf-8") == '{"x":1}\n'
    assert (tmp_path / "runtime" / "models" / "trade_model_v13.json").exists()
    assert res.freed_bytes > 0
    assert "ai_intelligence_preserved=true" in format_purged_logs(res)


def test_purge_dry_run_changes_nothing(tmp_path):
    _make_logs_tree(tmp_path)
    res = purge_stale_top_level_logs(tmp_path, dry_run=True)
    logs = tmp_path / "logs"
    assert (logs / "hypersmart_simulation_live.log").stat().st_size == 5000  # untouched
    assert (logs / "logs à envoyer.zip").exists()
    assert (logs / MOJIBAKE_LOGS_TO_SEND_DIRNAME).exists()
    assert res.freed_bytes > 0  # reports what WOULD be freed
