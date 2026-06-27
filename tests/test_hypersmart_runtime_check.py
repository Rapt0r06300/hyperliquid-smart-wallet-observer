from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.runtime.runtime_check import format_runtime_report, scan_runtime_files
from hl_observer.config.loader import load_settings
from hl_observer.runtime.hygiene import format_runtime_hygiene_report, scan_runtime_hygiene


def test_runtime_check_detects_db_in_logs(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "legacy.sqlite3").write_bytes(b"sqlite")
    config = AppConfig(runtime_root=tmp_path, database_path=tmp_path / "data" / "hypersmart.sqlite3")

    report = scan_runtime_files(config)

    assert len(report.logs_databases) == 1
    assert "databases_in_logs: 1" in format_runtime_report(report)


def test_runtime_check_default_db_is_not_logs(tmp_path):
    config = AppConfig(runtime_root=tmp_path)

    report = scan_runtime_files(config)

    assert "logs" not in [part.lower() for part in report.database_path.parts]


def test_hl_observer_runtime_check_warns_legacy_db_in_logs(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "hl_observer.sqlite3").write_bytes(b"sqlite")
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'hl_observer.sqlite3'}"

    report = scan_runtime_hygiene(settings, root=tmp_path)
    text = format_runtime_hygiene_report(report)

    assert report.databases_in_logs_count == 1
    assert "WARNING legacy DB in logs" in text
    assert "do not archive runtime files" in text
