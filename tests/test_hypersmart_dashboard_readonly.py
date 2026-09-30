from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.dashboard.exporter import export_dashboard


def test_dashboard_has_no_dangerous_buttons(tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite3", dashboard_dir=tmp_path / "dashboard", runtime_root=tmp_path)
    html = export_dashboard(config).read_text(encoding="utf-8").lower()

    assert "<button" not in html
    assert "connect wallet" not in html
    assert "private key" not in html
    assert "copy trade" not in html
