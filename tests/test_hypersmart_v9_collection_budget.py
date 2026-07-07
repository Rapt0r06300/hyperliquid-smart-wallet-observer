from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.collection.weight_budgeter import (
    AGGRESSIVE_SCRAPING_REFUSED,
    NETWORK_READ_DISABLED,
    RATE_LIMIT_BYPASS_REFUSED,
    RATE_LIMIT_GUARD,
    WEBSOCKET_LIMIT_GUARD,
    ReadOnlyBudgetRequest,
    estimate_readonly_rest_weight,
    format_budget_plan,
    plan_readonly_collection_budget,
)


def test_v9_budget_refuses_when_network_read_is_disabled():
    plan = plan_readonly_collection_budget(
        ReadOnlyBudgetRequest(all_mids_calls=1, light_info_calls=1)
    )

    assert plan.allowed is False
    assert NETWORK_READ_DISABLED in plan.refusal_reasons
    assert plan.execution == "forbidden"


def test_v9_budget_refuses_bypass_and_aggressive_scraping_requests():
    plan = plan_readonly_collection_budget(
        ReadOnlyBudgetRequest(
            network_read_enabled=True,
            bypass_requested=True,
            aggressive_scraping_requested=True,
        )
    )

    assert plan.allowed is False
    assert "BYPASS_OVERRIDE_ACTIVE" not in plan.warnings
    assert RATE_LIMIT_BYPASS_REFUSED in plan.refusal_reasons
    assert AGGRESSIVE_SCRAPING_REFUSED in plan.refusal_reasons


def test_v9_budget_estimates_official_read_weight_conservatively():
    request = ReadOnlyBudgetRequest(
        network_read_enabled=True,
        all_mids_calls=1,
        light_info_calls=2,
        default_info_calls=3,
        explorer_calls=1,
        time_range_items_expected=41,
    )

    assert estimate_readonly_rest_weight(request) == 2 + 4 + 60 + 40 + 60
    plan = plan_readonly_collection_budget(request)

    assert plan.allowed is True
    assert plan.safe_rest_budget == 840
    assert plan.rest_weight_remaining_after == 840 - 166


def test_v9_budget_rejects_cycles_above_safe_rest_margin():
    plan = plan_readonly_collection_budget(
        ReadOnlyBudgetRequest(
            network_read_enabled=True,
            default_info_calls=60,
            time_range_items_expected=500,
        )
    )

    assert plan.allowed is False
    assert RATE_LIMIT_GUARD in plan.refusal_reasons
    assert plan.estimated_rest_weight > plan.safe_rest_budget


def test_v9_budget_rejects_websocket_caps_above_official_unique_user_limit():
    plan = plan_readonly_collection_budget(
        ReadOnlyBudgetRequest(
            network_read_enabled=True,
            all_mids_calls=1,
            ws_connections=1,
            ws_new_connections_per_minute=1,
            ws_subscriptions=25,
            ws_unique_users=11,
            ws_messages_per_minute=20,
        )
    )

    assert plan.allowed is False
    assert WEBSOCKET_LIMIT_GUARD in plan.refusal_reasons
    assert plan.ws_ok is False


def test_v9_budget_allows_controlled_multi_egress_without_bypass_flags():
    one_egress = plan_readonly_collection_budget(
        ReadOnlyBudgetRequest(network_read_enabled=True, default_info_calls=50)
    )
    two_egress = plan_readonly_collection_budget(
        ReadOnlyBudgetRequest(network_read_enabled=True, default_info_calls=50, egress_count=2)
    )

    assert one_egress.allowed is False
    assert RATE_LIMIT_GUARD in one_egress.refusal_reasons
    assert two_egress.allowed is True
    assert "MULTI_EGRESS_REQUIRES_STICKY_SAFE_SHARDING" in two_egress.warnings
    assert RATE_LIMIT_BYPASS_REFUSED not in two_egress.refusal_reasons


def test_v9_budget_report_is_auditable_and_read_only():
    plan = plan_readonly_collection_budget(
        ReadOnlyBudgetRequest(network_read_enabled=True, all_mids_calls=1)
    )

    report = format_budget_plan(plan)

    assert "collection_budget=hyperliquid_read_only" in report
    assert "read_only=true" in report
    assert "execution=forbidden" in report


def test_v9_collection_budget_cli_reports_safe_budget_and_refuses_bad_caps():
    runner = CliRunner()
    ok = runner.invoke(
        app,
        [
            "collection-budget-plan",
            "--network-read",
            "--all-mids-calls",
            "1",
            "--default-info-calls",
            "3",
            "--time-range-items",
            "40",
            "--ws-unique-users",
            "10",
        ],
    )
    refused = runner.invoke(
        app,
        [
            "collection-budget-plan",
            "--network-read",
            "--ws-unique-users",
            "11",
        ],
    )

    assert ok.exit_code == 0
    assert "collection_budget=hyperliquid_read_only" in ok.output
    assert "allowed=true" in ok.output
    assert "execution=forbidden" in ok.output
    assert refused.exit_code == 2
    assert WEBSOCKET_LIMIT_GUARD in refused.output


def test_v9_fresh_data_plan_cli_includes_collection_budget(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh_budget.sqlite3"
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    from hl_observer.storage.database import init_db

    init_db(f"sqlite:///{db_path}")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "fresh-data-plan",
            "--network-read",
            "--coins",
            "BTC,ETH",
            "--max-hot-wallets",
            "10",
            "--gap-recovery",
        ],
    )

    assert result.exit_code == 0
    assert "fresh_data_plan=read_only_safe" in result.output
    assert "collection_budget=hyperliquid_read_only" in result.output
    assert "execution=forbidden" in result.output
