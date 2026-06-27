from pathlib import Path

from hl_observer.security.fake_data_scanner import scan_for_fake_data
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


def test_no_fabricated_data_generators_in_runtime():
    """Rule #1 (NO FAKE): the active runtime must invent nothing —
    no fake price / PnL / fill / wallet generator anywhere in src/hl_observer."""
    findings = scan_for_fake_data()
    assert findings == [], "\n".join(str(f) for f in findings)
