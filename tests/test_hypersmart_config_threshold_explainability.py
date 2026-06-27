from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.app.config import AppConfig, load_config
from hyper_smart_observer.copy_mode.copy_models import PositionView, SignalDecision, utc_now
from hyper_smart_observer.copy_mode.copy_signal_detector import detect_signal_candidates
from hyper_smart_observer.copy_mode.delta_detector import diff_position_snapshots
from hyper_smart_observer.dashboard.exporter import export_dashboard

ADDR = "0x" + "b" * 40


def test_launcher_simulation_env_aliases_drive_copy_runtime_thresholds(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_SIMULATION_MIN_EDGE_BPS", "35")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "6000")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE", "0.55")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS", "12")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_OPEN_POSITIONS", "25")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_POSITION_NOTIONAL", "125")

    cfg = load_config(tmp_path / "missing.env")

    assert cfg.copy_min_edge_required_bps == 35
    assert cfg.copy_max_signal_age_ms == 6000
    assert cfg.copy_min_liquidity_score == 0.55
    assert cfg.copy_max_degradation_bps == 12
    assert cfg.paper_max_open_trades == 25
    assert cfg.paper_max_position_notional == 125


def test_configurable_liquidity_threshold_rejects_only_below_active_threshold():
    now = utc_now()
    delta = diff_position_snapshots(
        [PositionView(ADDR, "BTC", 0, now, 50_000)],
        [PositionView(ADDR, "BTC", 1, now, 50_010)],
        observed_at=now,
    )[0]
    feature = SimpleNamespace(current_mid=50_000.0, spread_bps=2.0, liquidity_score=0.40)

    strict_signals, _ = detect_signal_candidates(
        [delta],
        leader_expected_edge_bps=100.0,
        leader_scores={ADDR: 95.0},
        market_features={"BTC": feature},
        min_liquidity_score=0.50,
    )
    loose_signals, _ = detect_signal_candidates(
        [delta],
        leader_expected_edge_bps=100.0,
        leader_scores={ADDR: 95.0},
        market_features={"BTC": feature},
        min_liquidity_score=0.30,
    )

    assert strict_signals[0].decision == SignalDecision.REJECT_NO_TRADE
    assert "LIQUIDITY_TOO_LOW" in strict_signals[0].refusal_reasons
    assert "LIQUIDITY_TOO_LOW" not in loose_signals[0].refusal_reasons


def test_dashboard_explains_active_thresholds_without_sensitive_material(tmp_path):
    cfg = AppConfig(
        runtime_root=tmp_path,
        database_path=tmp_path / "data" / "hs.sqlite3",
        reports_dir=tmp_path / "data" / "reports",
        dashboard_dir=tmp_path / "data" / "dashboard",
        copy_min_edge_required_bps=35,
        copy_max_signal_age_ms=6000,
        copy_min_liquidity_score=0.55,
        copy_max_degradation_bps=12,
        sensitive_key_material="must-not-render",
    )

    html = export_dashboard(cfg).read_text(encoding="utf-8")

    assert "Configuration active / seuils" in html
    assert "copy_min_edge_required_bps" in html
    assert "35" in html
    assert "copy_min_liquidity_score" in html
    assert "0.55" in html
    assert "must-not-render" not in html
    assert "sensitive_key_material" not in html
