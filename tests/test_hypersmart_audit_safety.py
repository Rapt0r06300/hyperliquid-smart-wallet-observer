from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.audit.safety_audit import run_safety_audit, write_audit_report
from hyper_smart_observer.dashboard.exporter import export_dashboard


def test_safety_audit_ok_for_temp_runtime(tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite3", dashboard_dir=tmp_path / "dashboard", runtime_root=tmp_path)
    export_dashboard(config)

    findings = run_safety_audit(config)

    assert all(finding.ok for finding in findings)


def test_safety_audit_report_falls_back_when_output_is_unwritable(tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite3", dashboard_dir=tmp_path / "dashboard", runtime_root=tmp_path)
    export_dashboard(config)
    blocked_output = tmp_path / "blocked_report.md"
    blocked_output.mkdir()

    report_path = write_audit_report(config, output=blocked_output)

    assert report_path != blocked_output
    assert report_path.exists()
    assert "original report path unavailable" in report_path.read_text(encoding="utf-8")
