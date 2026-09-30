from __future__ import annotations

import csv

from hl_observer.exports.decision_csv_logger import DecisionCsvRow, append_decision_csv


def test_decision_csv_logger_creates_header_once_across_appends(tmp_path) -> None:
    output = tmp_path / "nested" / "decisions.csv"

    append_decision_csv(
        output,
        [
            DecisionCsvRow(
                ts_ms=1,
                component="risk",
                coin="BTC",
                decision="NO_TRADE",
                reason="PAPER_GUARD",
            )
        ],
    )
    append_decision_csv(
        output,
        [
            DecisionCsvRow(
                ts_ms=2,
                component="risk",
                coin="ETH",
                decision="NO_TRADE",
                reason="PAPER_GUARD",
            )
        ],
    )

    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == [
        "ts_ms",
        "component",
        "coin",
        "decision",
        "reason",
        "edge_bps",
        "paper_only",
    ]
    assert sum(row == rows[0] for row in rows) == 1
    assert [row[2] for row in rows[1:]] == ["BTC", "ETH"]
    assert all(row[-1] == "True" for row in rows[1:])
