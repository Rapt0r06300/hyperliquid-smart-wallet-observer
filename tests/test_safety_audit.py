from pathlib import Path

from hl_observer.security.safety_audit import run_safety_audit
from hl_observer.security.secrets import contains_secret_pattern, scan_file_for_secret


def test_safety_audit_detects_env_secret_pattern(tmp_path):
    secret_file = tmp_path / "bad.env"
    secret_file.write_text("PRIVATE" + "_KEY=" + "abc123\n", encoding="utf-8")

    finding = scan_file_for_secret(secret_file)

    assert finding is not None
    assert contains_secret_pattern(secret_file.read_text(encoding="utf-8"))


def test_safety_audit_passes_project_baseline():
    result = run_safety_audit(Path.cwd())

    assert result.ok, result.findings
    assert result.checks["mainnet_disabled_in_env_example"]
    assert result.checks["live_executor_disabled_exists"]
