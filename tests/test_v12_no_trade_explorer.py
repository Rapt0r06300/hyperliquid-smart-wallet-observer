from hl_observer.validation.no_trade_analyzer import (
    build_no_trade_explorer,
    no_trade_precision,
    normalize_reasons,
)


def test_precision_preserved():
    assert no_trade_precision(0, 0) == 0.0
    assert no_trade_precision(3, 12) == 0.25


def test_empty_is_honest_empty_state():
    p = build_no_trade_explorer([])
    assert p["empty"] is True
    assert p["total"] == 0 and p["recognized"] == 0
    assert p["by_code"] == [] and p["by_category"] == {} and p["unknown_reasons"] == []


def test_aliases_fold_into_canonical():
    # REJECT_TOO_LATE + STALE_SIGNAL both map to SIGNAL_TOO_OLD
    p = build_no_trade_explorer(["REJECT_TOO_LATE", "STALE_SIGNAL", "SIGNAL_TOO_OLD"])
    codes = {row["reason_code"]: row["count"] for row in p["by_code"]}
    assert codes["SIGNAL_TOO_OLD"] == 3
    assert p["recognized"] == 3 and p["unknown"] == 0


def test_unknown_reason_surfaced_not_invented():
    p = build_no_trade_explorer(["TOTALLY_MADE_UP", "TOTALLY_MADE_UP", "MID_MISSING"])
    assert p["recognized"] == 1
    assert p["unknown"] == 2
    assert p["unknown_reasons"] == [{"reason": "TOTALLY_MADE_UP", "count": 2}]
    # the made-up reason must NOT appear among canonical codes
    assert all(row["reason_code"] != "TOTALLY_MADE_UP" for row in p["by_code"])


def test_grouping_and_counts_consistent():
    raw = ["LIQUIDITY_TOO_LOW", "SPREAD_TOO_WIDE", "MID_MISSING", "EXOTIC_MARKET_SKIPPED"]
    p = build_no_trade_explorer(raw, now_ms=1234)
    assert p["generated_at_ms"] == 1234
    assert sum(p["by_category"].values()) == p["recognized"]
    assert sum(p["by_severity"].values()) == p["recognized"]
    # EXOTIC_MARKET_SKIPPED -> BLOCKED_ASSET (alias)
    assert any(row["reason_code"] == "BLOCKED_ASSET" for row in p["by_code"])


def test_by_code_rows_have_display_fields():
    p = build_no_trade_explorer(["MID_MISSING"])
    row = p["by_code"][0]
    assert set(row) == {
        "reason_code", "count", "severity", "category",
        "is_retriable", "dashboard_message", "next_action",
    }
    assert row["dashboard_message"].strip() and row["next_action"].strip()


def test_retriable_count():
    # SOURCE_STALE retriable, BLOCKED_ASSET not retriable
    p = build_no_trade_explorer(["SOURCE_STALE", "SOURCE_STALE", "BLOCKED_ASSET"])
    assert p["retriable_count"] == 2


def test_normalize_reasons_split():
    canonical, unknown = normalize_reasons(["MID_MISSING", "NOPE"])
    assert canonical == ["MID_MISSING"]
    assert unknown == ["NOPE"]
