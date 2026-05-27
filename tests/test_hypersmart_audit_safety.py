from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.audit.safety_audit import run_safety_audit
from hyper_smart_observer.dashboard.exporter import export_dashboard


def test_safety_audit_ok_for_temp_runtime(tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite3", dashboard_dir=tmp_path / "dashboard", runtime_root=tmp_path)
    export_dashboard(config)

    findings = run_safety_audit(config)

    assert all(finding.ok for finding in findings)
