import csv

from hl_observer.exports.decision_csv_logger import DecisionCsvRow, append_decision_csv


def test_decision_csv_logger_writes_header_and_rows(tmp_path):
    path = tmp_path / "decisions.csv"
    append_decision_csv(path, [DecisionCsvRow(ts_ms=1, component="risk", coin="HYPE", decision="NO_TRADE", reason="CONFLICTING_LEADERS")])
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows[0]["decision"] == "NO_TRADE"
    assert rows[0]["paper_only"] == "True"
