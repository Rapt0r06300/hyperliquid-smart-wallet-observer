from pathlib import Path

from hl_observer.security.fake_data_scanner import scan_for_fake_data
from hl_observer.security.safety_audit import _iter_scannable_files, run_safety_audit
from hl_observer.security.secrets import contains_secret_pattern, scan_file_for_secret


def test_safety_audit_detects_env_secret_pattern(tmp_path):
    secret_file = tmp_path / "bad.env"
    secret_file.write_text("PRIVATE" + "_KEY=" + "abc123\n", encoding="utf-8")

    finding = scan_file_for_secret(secret_file)

    assert finding is not None
    assert contains_secret_pattern(secret_file.read_text(encoding="utf-8"))


def test_scan_file_for_secret_detects_openai_key(tmp_path):
    secret_file = tmp_path / "bad.txt"
    secret_file.write_text("OPENAI_API_KEY=sk-proj-" + "a" * 24 + "\n", encoding="utf-8")

    finding = scan_file_for_secret(secret_file)

    assert finding is not None
    assert finding.path == secret_file
    assert finding.pattern == "openai_key"


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


def test_safety_audit_does_not_scan_embedded_third_party_runtime(tmp_path):
    app_file = tmp_path / "src" / "app.py"
    third_party = tmp_path / "portable_runtime" / "python" / "Lib" / "site-packages" / "vendor.py"
    embedded_python = tmp_path / "tools" / "python" / "Lib" / "site-packages" / "vendor.py"
    transient = tmp_path / ".portable-preflight-old" / "bad.env"
    app_file.parent.mkdir(parents=True)
    third_party.parent.mkdir(parents=True)
    embedded_python.parent.mkdir(parents=True)
    transient.parent.mkdir(parents=True)
    app_file.write_text("SAFE = True\n", encoding="utf-8")
    third_party.write_text("PRIVATE_KEY = 'third-party-license-token'\n", encoding="utf-8")
    embedded_python.write_text("PRIVATE_KEY = 'third-party-license-token'\n", encoding="utf-8")
    transient.write_text("PRIVATE_KEY=pytest-fixture\n", encoding="utf-8")

    files = _iter_scannable_files(tmp_path)

    assert app_file in files
    assert third_party not in files
    assert embedded_python not in files
    assert transient not in files


def test_safety_audit_tolerates_refusal_guard_but_detects_runtime_exchange(tmp_path, monkeypatch):
    src = tmp_path / "src" / "hl_observer"
    tests = tmp_path / "tests"
    (src / "ops").mkdir(parents=True)
    (src / "execution").mkdir(parents=True)
    tests.mkdir()
    (src / "ops" / "validation_portable.py").write_text(
        "BLOCKED = '/exchange'\n", encoding="utf-8"
    )
    (src / "execution" / "live_executor_disabled.py").write_text("LOCKED = True\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "HL_ENABLE_MAINNET_EXECUTION=false\n", encoding="utf-8"
    )
    for name in ("test_no_mainnet_execution.py", "test_safety_audit.py", "test_testnet_locked.py"):
        (tests / name).write_text("# presence proof\n", encoding="utf-8")
    monkeypatch.setattr("hl_observer.security.safety_audit.auditer_l_environnement", lambda: type(
        "Audit", (), {"ok": True, "alerte": ""}
    )())

    policy_only = run_safety_audit(tmp_path)
    assert policy_only.checks["no_exchange_endpoint_in_runtime_source"] is True

    (src / "client.py").write_text("URL = '/exchange'\n", encoding="utf-8")
    operational = run_safety_audit(tmp_path)
    assert operational.checks["no_exchange_endpoint_in_runtime_source"] is False
