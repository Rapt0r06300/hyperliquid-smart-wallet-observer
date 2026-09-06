from hl_observer.exports.csv_logging import CsvSignalLogger


def test_csv_signal_logger_writes_header_for_new_file(tmp_path) -> None:
    path = tmp_path / "signals.csv"
    CsvSignalLogger(path, fieldnames=("symbol", "edge_bps")).append(
        {"symbol": "BTC", "edge_bps": 1.25}
    )
    assert path.read_text(encoding="utf-8").splitlines() == [
        "symbol,edge_bps",
        "BTC,1.25",
    ]
