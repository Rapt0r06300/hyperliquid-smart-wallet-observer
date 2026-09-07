from __future__ import annotations

import csv

from hl_observer.exports.csv_logging import CsvSignalLogger


def test_csv_logger_creates_header_once_and_ignores_extra_fields(tmp_path) -> None:
    output = tmp_path / "nested" / "signals.csv"
    logger = CsvSignalLogger(output, fieldnames=("coin", "signal"))

    logger.append({"coin": "BTC", "signal": "PAPER", "ignored": "secret"})
    logger.append({"coin": "ETH", "signal": "NO_TRADE"})

    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows == [
        ["coin", "signal"],
        ["BTC", "PAPER"],
        ["ETH", "NO_TRADE"],
    ]
