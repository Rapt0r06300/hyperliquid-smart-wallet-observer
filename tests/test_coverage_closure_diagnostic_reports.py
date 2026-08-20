from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from hl_observer.simulation import diagnostic_reports as dr
from hl_observer.simulation.log_metrics import LogMetricsReport


def _metrics(**overrides) -> LogMetricsReport:
    m = LogMetricsReport(source_dir=Path("logs"), source_files=())
    m.total_decisions = 10
    m.accepted = 4
    m.refused = 6
    m.positive_events = 3
    m.negative_events = 2
    m.gross_pnl_usdc = 10.0
    m.net_pnl_usdc = -2.0
    m.net_gains_usdc = 3.0
    m.net_losses_usdc = -2.0
    m.fees_usdc = 3.0
    m.reasons = Counter({
        "STALE_SIGNAL": 2,
        "NO_MATCHING_PAPER_POSITION_FOR_CLOSE": 1,
        "COPY_DEGRADATION_TOO_HIGH": 1,
        "PRICE_DEVIATION_TOO_HIGH": 1,
        "ADD_WITHOUT_ORIGINAL_OPEN_REFUSED": 1,
    })
    m.fees_by_action = defaultdict(float, {"OPEN": 2.0, "CLOSE": 1.0})
    m.pnl_by_wallet = defaultdict(float, {"w1": -2.0, "w2": 1.0})
    m.pnl_by_coin = defaultdict(float, {"BTC": -3.0, "ETH": 2.0})
    m.pnl_by_action = defaultdict(float, {"OPEN": -1.0, "CLOSE": 0.5})
    m.edge_values = [-9999.0, -1.0, 0.0, 20.0, 30.0, 70.0]
    m.signal_age_values = [100, 4_000, 25_000]
    m.edge_sentinel_count = 1
    m.edge_negative_count = 1
    m.edge_positive_count = 4
    for key, value in overrides.items():
        setattr(m, key, value)
    return m


def test_root_cause_reports_all_known_causes(monkeypatch, tmp_path) -> None:
    metrics = _metrics()
    monkeypatch.setattr(dr, "analyze_logs_streaming", lambda path: metrics)
    monkeypatch.setattr(dr, "build_recommendations", lambda value: ["fix-a", "fix-b"])
    report = dr.build_root_cause_from_logs(tmp_path)
    text = dr.format_diagnostic_report(report)
    for marker in (
        "PNL_NET_NEGATIF_APRES_COUTS",
        "SIGNAUX_TROP_VIEUX",
        "EDGE_NON_MESURABLE_OU_NEGATIF",
        "FERMETURES_SANS_POSITION_PAPER",
        "DEGRADATION_COPIE_TROP_FORTE",
        "PRIX_TROP_ELOIGNE_DU_LEADER",
        "FRAIS_TROP_IMPORTANTS_VS_EDGE",
        "fix-a",
        "execution=forbidden",
    ):
        assert marker in text


def test_root_cause_default_and_profitability_interpretations(monkeypatch, tmp_path) -> None:
    neutral = _metrics(
        net_pnl_usdc=0.0,
        gross_pnl_usdc=0.0,
        fees_usdc=0.0,
        reasons=Counter(),
        edge_sentinel_count=0,
        edge_negative_count=0,
    )
    monkeypatch.setattr(dr, "analyze_logs_streaming", lambda path: neutral)
    monkeypatch.setattr(dr, "build_recommendations", lambda value: [])
    assert "PAS_DE_CAUSE_DOMINANTE" in dr.format_diagnostic_report(dr.build_root_cause_from_logs(tmp_path))

    positive = _metrics(net_pnl_usdc=1.0)
    monkeypatch.setattr(dr, "analyze_logs_streaming", lambda path: positive)
    assert "PnL net positif" in dr.format_diagnostic_report(dr.build_profitability_diagnostics(tmp_path))

    cost_destroyed = _metrics(gross_pnl_usdc=1.0, net_pnl_usdc=-1.0)
    monkeypatch.setattr(dr, "analyze_logs_streaming", lambda path: cost_destroyed)
    assert "couts detruisent" in dr.format_diagnostic_report(dr.build_profitability_diagnostics(tmp_path))

    negative = _metrics(gross_pnl_usdc=-1.0, net_pnl_usdc=-2.0)
    monkeypatch.setattr(dr, "analyze_logs_streaming", lambda path: negative)
    assert "filtrage edge" in dr.format_diagnostic_report(dr.build_profitability_diagnostics(tmp_path))


def test_all_specialized_diagnostics(monkeypatch, tmp_path) -> None:
    metrics = _metrics()
    monkeypatch.setattr(dr, "analyze_logs_streaming", lambda path: metrics)

    assert "STALE_SIGNAL: 2" in dr.format_diagnostic_report(dr.build_refusal_breakdown(tmp_path))
    assert "OPEN: 2.000000" in dr.format_diagnostic_report(dr.build_cost_drag_diagnostics(tmp_path))

    position = dr.format_diagnostic_report(dr.build_position_matching_diagnostics(tmp_path))
    assert "orphan_close_count=1" in position
    assert "orphan_close_ratio=0.10000000" in position
    assert "add_without_original_open_count=1" in position

    stale = dr.format_diagnostic_report(dr.build_stale_signal_diagnostics(tmp_path))
    assert "measured_signal_ages=3" in stale
    assert "stale_over_3000_ms=2" in stale
    assert "stale_over_20000_ms=1" in stale

    assert "w1: -2.000000" in dr.format_diagnostic_report(dr.build_wallet_loss_diagnostics(tmp_path))
    assert "BTC: -3.000000" in dr.format_diagnostic_report(dr.build_coin_loss_diagnostics(tmp_path))
    assert "OPEN: -1.000000" in dr.format_diagnostic_report(dr.build_action_loss_diagnostics(tmp_path))

    edge = dr.format_diagnostic_report(dr.build_edge_distribution_diagnostics(tmp_path))
    for bucket in ("sentinel_-9999", "negative", "0_to_25", "25_to_60", "60_plus"):
        assert bucket in edge

    assert dr.build_timing_distribution_diagnostics(tmp_path).name == "stale_signal_diagnostics"


def test_zero_denominators_and_rank_order(monkeypatch, tmp_path) -> None:
    metrics = _metrics(total_decisions=0, signal_age_values=[])
    monkeypatch.setattr(dr, "analyze_logs_streaming", lambda path: metrics)
    position = dr.format_diagnostic_report(dr.build_position_matching_diagnostics(tmp_path))
    stale = dr.format_diagnostic_report(dr.build_stale_signal_diagnostics(tmp_path))
    assert "orphan_close_ratio=0.00000000" in position
    assert "stale_over_3000_ratio=0.00000000" in stale
    assert "stale_over_20000_ratio=0.00000000" in stale

    assert dr._rank_lines({"a": 1.0, "b": 3.0, "c": 2.0}, reverse=True, limit=2) == [
        "- b: 3.000000",
        "- c: 2.000000",
    ]
    assert dr._rank_lines({"a": 1.0, "b": -1.0}, reverse=False, limit=1) == ["- b: -1.000000"]
