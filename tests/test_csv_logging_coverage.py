from __future__ import annotations

import csv

from hl_observer.exports.csv_logging import CsvSignalLogger


def test_csv_signal_logger_writes_header_once_and_ignores_extra_fields(tmp_path) -> None:
    path = tmp_path / "nested" / "signals.csv"
    logger = CsvSignalLogger(path, fieldnames=("signal", "score"))

    logger.append({"signal": "copy", "score": 1.25, "ignored": "extra"})
    logger.append({"signal": "lead-lag"})

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows == [
        ["signal", "score"],
        ["copy", "1.25"],
        ["lead-lag", ""],
    ]
