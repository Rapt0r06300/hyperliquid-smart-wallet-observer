from __future__ import annotations

from pathlib import Path

from hl_observer.copying.realtime_magic_score import RealtimeCopyRiskConfig
from hl_observer.scanner.missed_opportunity_logger import write_missed_opportunity_reports
from hl_observer.scanner.opportunity_detector import detect_missed_opportunity
from hl_observer.scanner.priority_queue import select_wallets_for_warm_scan
from hl_observer.scanner.scan_budget import evaluate_warm_scan_budget, estimate_warm_scan_rest_cost
from hl_observer.scanner.scanner_models import ScanBudget, SignalObservation, WalletPriorityInput
from hl_observer.scanner.scheduler import default_scan_schedule
from hl_observer.scanner.fresh_scan_strategy import (
    FreshScanStrategyRequest,
    format_fresh_scan_strategy,
    plan_fresh_scan_strategy,
)
from hl_observer.scanner.throughput_planner import (
    ThroughputRequest,
    format_throughput_plan,
    plan_safe_high_throughput_scan,
)
from hl_observer.scanner.wallet_priority import score_wallet_priority


GOOD_WALLET = "0x" + "a" * 40
SECOND_WALLET = "0x" + "b" * 40
THIRD_WALLET = "0x" + "c" * 40


def test_wallet_priority_rejects_truncated_address() -> None:
    result = score_wallet_priority(WalletPriorityInput(wallet_address="0xabc...def", now_ms=1000))
    assert result.status == "REJECTED"
    assert result.reasons == ["TRUNCATED_WALLET_ADDRESS"]


def test_wallet_priority_prefers_fresh_active_quality_wallet() -> None:
    fresh = score_wallet_priority(
        WalletPriorityInput(
            wallet_address=GOOD_WALLET,
            trades_count=30,
            observed_notional_usdt=250_000,
            last_seen_ms=99_500,
            now_ms=100_000,
            wallet_quality_score=90,
            consistency_score=80,
            copyability_score=85,
            consensus_hits=2,
        )
    )
    stale = score_wallet_priority(
        WalletPriorityInput(
            wallet_address=SECOND_WALLET,
            trades_count=1,
            observed_notional_usdt=1_000,
            last_seen_ms=1_000,
            now_ms=100_000,
            wallet_quality_score=40,
            consistency_score=30,
            copyability_score=30,
        )
    )
    assert fresh.priority_score > stale.priority_score
    assert fresh.status == "PRIORITIZED"


def test_scan_selection_respects_max_leaders_and_logs_skips() -> None:
    candidates = [
        score_wallet_priority(WalletPriorityInput(wallet_address=GOOD_WALLET, trades_count=20, observed_notional_usdt=100_000, last_seen_ms=99_000, now_ms=100_000, wallet_quality_score=90, consistency_score=90, copyability_score=90)),
        score_wallet_priority(WalletPriorityInput(wallet_address=SECOND_WALLET, trades_count=10, observed_notional_usdt=80_000, last_seen_ms=99_000, now_ms=100_000, wallet_quality_score=80, consistency_score=80, copyability_score=80)),
        score_wallet_priority(WalletPriorityInput(wallet_address=THIRD_WALLET, trades_count=8, observed_notional_usdt=70_000, last_seen_ms=99_000, now_ms=100_000, wallet_quality_score=70, consistency_score=70, copyability_score=70)),
    ]
    result = select_wallets_for_warm_scan(candidates, ScanBudget(max_leaders_per_run=2, network_read_enabled=True))
    assert len(result.selected_wallets) == 2
    assert any(item.reason == "WALLET_SKIPPED_BY_BUDGET" for item in result.skipped)


def test_scan_selection_refuses_when_network_disabled() -> None:
    candidates = [score_wallet_priority(WalletPriorityInput(wallet_address=GOOD_WALLET, now_ms=1000))]
    result = select_wallets_for_warm_scan(candidates, ScanBudget(max_leaders_per_run=1, network_read_enabled=False))
    assert result.selected_wallets == []
    assert result.stopped_reason == "NETWORK_READ_DISABLED"
    assert result.skipped[0].reason == "NETWORK_READ_DISABLED"


def test_warm_scan_budget_is_conservative() -> None:
    assert estimate_warm_scan_rest_cost(wallets=3, fills_expected_per_wallet=200) == 45
    allowed = evaluate_warm_scan_budget(ScanBudget(max_leaders_per_run=3, rest_weight_remaining=100, network_read_enabled=True), requested_wallets=3)
    blocked = evaluate_warm_scan_budget(ScanBudget(max_leaders_per_run=3, rest_weight_remaining=10, network_read_enabled=True), requested_wallets=3)
    assert allowed.allowed is True
    assert blocked.reason == "RATE_LIMIT_GUARD"


def test_missed_opportunity_detects_stale_and_missing_mid() -> None:
    stale = detect_missed_opportunity(
        SignalObservation(
            signal_id="s1",
            wallet_address=GOOD_WALLET,
            coin="BTC",
            action_type="OPEN_LONG",
            observed_at_ms=0,
            now_ms=120_000,
            current_mid=100.0,
            edge_remaining_bps=20.0,
        ),
        max_signal_age_ms=60_000,
    )
    missing_mid = detect_missed_opportunity(
        SignalObservation(
            signal_id="s2",
            wallet_address=GOOD_WALLET,
            coin="ETH",
            action_type="OPEN_SHORT",
            observed_at_ms=100_000,
            now_ms=101_000,
            current_mid=None,
            edge_remaining_bps=20.0,
        )
    )
    assert stale is not None and stale.reason == "STALE_SIGNAL"
    assert missing_mid is not None and missing_mid.reason == "MISSING_CURRENT_MID"


def test_missed_opportunity_report_exports_all_formats(tmp_path: Path) -> None:
    missed = detect_missed_opportunity(
        SignalObservation(
            signal_id="s1",
            wallet_address=GOOD_WALLET,
            coin="BTC",
            action_type="OPEN_LONG",
            observed_at_ms=0,
            now_ms=120_000,
            current_mid=100.0,
            edge_remaining_bps=20.0,
        )
    )
    assert missed is not None
    paths = write_missed_opportunity_reports([missed], output_dir=tmp_path)
    assert paths["json"].exists()
    assert paths["csv"].exists()
    assert paths["markdown"].exists()
    assert "STALE_SIGNAL" in paths["markdown"].read_text(encoding="utf-8")


def test_default_schedule_matches_safe_scan_architecture() -> None:
    schedule = default_scan_schedule()
    assert [item.tier.value for item in schedule] == ["COLD", "WARM", "HOT"]
    assert schedule[1].max_wallets == 3
    assert schedule[2].max_wallets == 10
    assert all("execution" not in item.description.lower() for item in schedule)


def test_paper_config_is_locked_to_1000_and_prudent_caps() -> None:
    cfg = RealtimeCopyRiskConfig()
    assert cfg.starting_equity_usdt == 1000.0
    assert cfg.max_position_notional_usdt == 50.0
    assert cfg.max_total_exposure_usdt == 200.0


def test_throughput_plan_refuses_bypass_and_aggressive_scraping() -> None:
    plan = plan_safe_high_throughput_scan(
        ThroughputRequest(
            requested_wallets=50_000,
            network_read_enabled=True,
            bypass_requested=True,
            aggressive_scraping_requested=True,
        )
    )

    assert plan.starts is False
    assert plan.execution == "forbidden"
    assert plan.selected_wallets == 0
    assert "BYPASS_OVERRIDE_ACTIVE" not in plan.warnings
    assert "RATE_LIMIT_BYPASS_REFUSED" in plan.refusal_reasons
    assert "AGGRESSIVE_SCRAPING_REFUSED" in plan.refusal_reasons


def test_throughput_plan_refuses_network_disabled_without_crashing() -> None:
    plan = plan_safe_high_throughput_scan(ThroughputRequest(requested_wallets=50, network_read_enabled=False))

    assert plan.starts is False
    assert plan.selected_wallets == 0
    assert plan.refusal_reasons == ["NETWORK_READ_DISABLED"]


def test_throughput_plan_rotates_instead_of_refusing_oversized_scan() -> None:
    plan = plan_safe_high_throughput_scan(
        ThroughputRequest(
            requested_wallets=50,
            network_read_enabled=True,
            rest_weight_remaining=100,
            max_leaders_per_run=50,
            fills_expected_per_wallet=200,
        )
    )

    assert plan.starts is True
    assert plan.status == "SAFE_ROTATION_ACTIVE"
    assert 0 < plan.selected_wallets < 50
    assert plan.deferred_wallets == 50 - plan.selected_wallets
    assert plan.estimated_rest_weight <= 100
    assert "SAFE_ROTATION_ACTIVE" in plan.warnings


def test_throughput_plan_caps_user_specific_ws_to_ten() -> None:
    plan = plan_safe_high_throughput_scan(
        ThroughputRequest(
            requested_wallets=50,
            network_read_enabled=True,
            ws_enabled=True,
            ws_requested_unique_users=50,
            max_leaders_per_run=50,
            rest_weight_remaining=1200,
        )
    )

    assert plan.user_specific_ws_users == 10
    assert plan.ws_subscriptions_cap == 1000
    assert "read_only=true" in format_throughput_plan(plan)


def test_fresh_scan_strategy_turns_stale_pressure_into_continuous_safe_scan() -> None:
    plan = plan_fresh_scan_strategy(
        FreshScanStrategyRequest(
            requested_wallet_universe=50_000,
            network_read_enabled=True,
            cycle_seconds=15,
            stale_signal_count=5_000,
            fresh_leader_count=0,
            fresh_delta_count=0,
            public_trade_wallet_cap_requested=10_000,
            leaders_per_user_stream=25,
        )
    )
    text = format_fresh_scan_strategy(plan)

    assert plan.status == "FRESH_SCAN_ACTIVE"
    assert plan.public_trade_scan_every_polls == 1
    assert plan.public_trade_wallet_cap == 10_000
    assert plan.user_fills_ws_users == 10
    assert plan.stale_pressure == "CRITICAL"
    assert plan.execution == "forbidden"
    assert "real_orders_created=0" in text
    assert "simulation_positions_are_virtual=true" in text


def test_fresh_scan_strategy_refuses_bypass_and_aggressive_scraping() -> None:
    plan = plan_fresh_scan_strategy(
        FreshScanStrategyRequest(
            requested_wallet_universe=50_000,
            network_read_enabled=True,
            bypass_requested=True,
            aggressive_scraping_requested=True,
        )
    )

    assert plan.scanner_starts is False
    assert "RATE_LIMIT_BYPASS_REFUSED" in plan.refusal_reasons
    assert "AGGRESSIVE_SCRAPING_REFUSED" in plan.refusal_reasons


def test_magic_bot_research_docs_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in [
        "docs/research/MAGIC_BOT_OSINT_RESEARCH.md",
        "docs/research/MAGIC_BOT_CLAIMS_MATRIX.md",
        "docs/research/HYPERLIQUID_DATA_SOURCES_MAP.md",
        "docs/research/HYPERSMART_FAST_SCAN_DESIGN.md",
    ]:
        path = root / relative
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "guaranteed profit" in text or "profit" in text.lower()
