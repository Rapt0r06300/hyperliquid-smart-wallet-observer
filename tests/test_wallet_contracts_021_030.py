from __future__ import annotations

from hl_observer.wallets.api_budget import starvation_receipt
from hl_observer.wallets.auto_watchlist import discovery_to_scanner_receipt
from hl_observer.wallets.discovery import validate_wallet_address_observation
from hl_observer.wallets.leader_hotness import separate_activity_quality
from hl_observer.wallets.leaderboard_full_address_extractor import address_observation_receipt
from hl_observer.wallets.leaderboard_parser import schema_drift_receipt
from hl_observer.wallets.leaderboard_source import source_provenance_receipt
from hl_observer.wallets.multi_source_merge import WalletRef, compare_discovery_sources
from hl_observer.wallets.tiered_scanner import assign_tiers, tier_fairness_receipt
from hl_observer.wallets.top500_bootstrap import retain_outside_top500


def test_wallet_address_contract_rejects_truncation() -> None:
    assert validate_wallet_address_observation("0x" + "a" * 40)["status"] == "PROVEN"
    assert validate_wallet_address_observation("0xaaaa…bbbb")["status"] == "UNMEASURABLE"


def test_leaderboard_source_provenance_is_explicit() -> None:
    receipt = source_provenance_receipt(
        method="public_api",
        source_url="https://example.invalid/leaderboard",
        captured_at_ms=1_700_000_000_000,
    )
    assert receipt["status"] == "PROVEN"
    assert receipt["paper_read_only"] is True


def test_schema_drift_receipt_covers_expected_fields() -> None:
    receipt = schema_drift_receipt(
        [{"address": "0x" + "a" * 40, "score": 1.0}],
        expected_fields={"address", "score"},
    )
    assert receipt["status"] == "PROVEN"
    assert receipt["missing"] == []


def test_full_address_payload_is_observable() -> None:
    receipt = address_observation_receipt({"address": "0x" + "b" * 40})
    assert receipt["status"] == "PROVEN"


def test_source_comparison_reports_observed_wallets_only() -> None:
    address = "0x" + "c" * 40
    receipt = compare_discovery_sources(
        [
            WalletRef(address, "leaderboard", 0.8, 1),
            WalletRef(address, "explorer", 0.7, 2),
        ]
    )
    assert receipt["status"] == "PROVEN"
    assert receipt["wallet_count"] == 1


def test_tier_fairness_reports_ws_capacity() -> None:
    plans = assign_tiers({"wallet-a": 1.0, "wallet-b": 0.5}, max_ws=1)
    receipt = tier_fairness_receipt(plans, max_ws=1)
    assert receipt["status"] == "PROVEN"
    assert receipt["hot_count"] == 1
    assert receipt["ws_capacity_ok"] is True


def test_top500_bootstrap_retains_outside_addresses() -> None:
    receipt = retain_outside_top500(["a", "b", "c"], top_limit=2)
    assert receipt["status"] == "PROVEN"
    assert receipt["retained"] == ["c"]


def test_api_budget_marks_starvation_when_wait_exceeds_bound() -> None:
    receipt = starvation_receipt(requested_weight=10, wait_ms=101, max_wait_ms=100)
    assert receipt["status"] == "PROVEN"
    assert receipt["starved"] is True


def test_activity_quality_keeps_activity_and_quality_separate() -> None:
    receipt = separate_activity_quality(recent_trade_count=3, quality_score=0.5)
    assert receipt["status"] == "PROVEN"
    assert receipt["recent_trade_count"] == 3
    assert receipt["quality_score"] == 0.5


def test_discovery_scanner_receipt_requires_persistence() -> None:
    receipt = discovery_to_scanner_receipt(discovered=3, selected=2, persisted=2)
    assert receipt["status"] == "PROVEN"
    assert receipt["persisted"] == 2
