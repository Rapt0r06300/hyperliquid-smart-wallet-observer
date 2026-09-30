from __future__ import annotations

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.release.prompt_coverage import (
    CoverageRow,
    REQUIRED_FAMILIES,
    evaluate_prompt_coverage,
    verify_non_deletion,
)


def test_prompt_coverage_lists_all_major_families():
    family_ids = {family.family_id for family in REQUIRED_FAMILIES}

    expected = {
        "SECURITY",
        "INTERNET_RESEARCH",
        "RUNTIME_ARCHIVE",
        "LOGS_LOSSES",
        "POSITION_REPRODUCTION",
        "DELTA_DETECTOR",
        "SIGNAL_CANDIDATE",
        "PAPER_CHAIN",
        "MULTI_POSITION",
        "REALTIME_EVENT_BUS",
        "REALTIME_RECOVERY",
        "RECONNECT_BACKFILL",
        "LIVE_PNL",
        "BEGINNER_UI",
        "METAGRAPHS",
        "COPY_RUN",
        "WEBSOCKET_BOUNDED",
        "LOCAL_SCAN",
        "DATA_ACQUISITION_ENGINE",
        "REQUEST_BUDGET_MANAGER",
        "PERSISTENT_FETCH_QUEUE",
        "HISTORICAL_BACKFILL_ENGINE",
        "CACHE_TTL_BACKOFF",
        "DATA_QUALITY_GATE",
        "WALLET_UNIVERSE",
        "EDGE_REMAINING",
        "ANTI_OVERFIT",
        "PROFIT_OPTIMIZER",
        "NO_TRADE",
        "DASHBOARD_TRUTH",
        "QUALITY_GATES",
        "CHATGPT_SUMMARY",
    }

    assert expected.issubset(family_ids)
    assert len(REQUIRED_FAMILIES) >= 40


def test_non_deletion_check_blocks_missing_family():
    ok, missing = verify_non_deletion(
        (
            CoverageRow("SECURITY", "Security", "DONE"),
            CoverageRow("LIVE_PNL", "Live PnL", "PARTIAL"),
        )
    )

    assert ok is False
    assert missing == ["LIVE_PNL"]


def test_prompt_coverage_command_writes_reports():
    result = CliRunner().invoke(app, ["prompt-coverage-audit"])

    assert result.exit_code == 0
    assert "mega_v1_prompt_coverage=tracked" in result.output
    assert "todo_or_partial=0" in result.output


def test_non_deletion_check_command_has_no_todo_or_partial():
    result = CliRunner().invoke(app, ["non-deletion-check"])

    assert result.exit_code == 0
    assert "non_deletion_check=tracked" in result.output
    assert "todo_or_partial=0" in result.output


def test_prompt_coverage_report_mentions_prompt_coverage():
    audit = evaluate_prompt_coverage()

    assert audit.report_path.exists()
    assert audit.non_deletion_path.exists()
    assert "MEGA V1 Prompt Coverage Audit" in audit.report_path.read_text(encoding="utf-8")
    assert "Non-Deletion" in audit.non_deletion_path.read_text(encoding="utf-8")
