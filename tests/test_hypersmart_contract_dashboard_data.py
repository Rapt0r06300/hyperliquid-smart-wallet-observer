import pytest
from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.dashboard.exporter import export_dashboard
import os

def test_dashboard_data_export(tmp_path):
    config = AppConfig(
        runtime_root=tmp_path,
        database_path=tmp_path / "dash_test.sqlite3",
        dashboard_dir=tmp_path / "dashboard",
        reports_dir=tmp_path / "reports"
    )

    # Ensure dirs exist
    config.dashboard_dir.mkdir(parents=True)
    config.reports_dir.mkdir(parents=True)

    # Initialize DB
    from hyper_smart_observer.storage.database import initialize_database
    initialize_database(config)

    path = export_dashboard(config)
    assert path.exists()
    assert path.suffix == ".html"
    content = path.read_text(encoding="utf-8")
    assert "HyperSmart" in content
