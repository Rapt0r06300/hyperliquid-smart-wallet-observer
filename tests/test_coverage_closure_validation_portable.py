from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import hl_observer.ops.validation_portable as portable


def test_hash_json_and_write_evidence(tmp_path) -> None:
    source = tmp_path / "x.bin"
    source.write_bytes(b"abc")
    digest, size = portable._sha256(source)
    assert digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert size == 3
    payload_path = tmp_path / "payload.json"
    payload_path.write_text('{"a": 1}', encoding="utf-8")
    assert portable._json(payload_path) == {"a": 1}
    out = portable.write_evidence(tmp_path / "nested" / "evidence.json", {"ok": True, "x": 2})
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8")) == {"ok": True, "x": 2}
    assert not list(out.parent.glob(".*.tmp"))


def test_hermetic_environment_requires_windows_root_and_builds_isolated_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SYSTEMROOT", raising=False)
    monkeypatch.delenv("WINDIR", raising=False)
    with pytest.raises(RuntimeError, match="SystemRoot/WINDIR absent"):
        portable._hermetic_environment(tmp_path, tmp_path / "guard")

    system = tmp_path / "Windows"
    monkeypatch.setenv("SYSTEMROOT", str(system))
    monkeypatch.setenv("WINDIR", str(system))
    monkeypatch.setenv("COMSPEC", "cmd.exe")
    env = portable._hermetic_environment(tmp_path, tmp_path / "guard")
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["PIP_NO_INDEX"] == "1"
    assert env["HL_ENABLE_MAINNET_EXECUTION"] == "0"
    assert env["HL_ENABLE_TESTNET_EXECUTION"] == "0"
    assert env["REAL_MAINNET_TRADING"] == "false"
    assert env["HYPERSMART_PORTABLE_AUDIT_ROOT"] == str(tmp_path)
    assert Path(env["TEMP"]).is_dir()
    assert Path(env["HOME"]).is_dir()
    assert "COMSPEC" in env

    pytest_env = portable._pytest_environment(env)
    assert "HYPERSMART_PORTABLE_AUDIT_ROOT" not in pytest_env
    assert "HYPERSMART_PORTABLE_AUDIT_LOG" not in pytest_env
    assert pytest_env["PIP_NO_INDEX"] == "1"


def test_install_sitecustomize_validates_embedded_pth(tmp_path) -> None:
    root = tmp_path / "release"
    python_dir = root / "tools" / "python"
    guard = python_dir / "Lib" / "site-packages"
    python_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="one embedded"):
        portable._install_sitecustomize(root, guard)

    pth = python_dir / "python311._pth"
    pth.write_text("python311.zip\n.\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Lib"):
        portable._install_sitecustomize(root, guard)

    pth.write_text("python311.zip\nLib\\site-packages\nimport site\n", encoding="utf-8")
    result = portable._install_sitecustomize(root, guard)
    assert result["ok"] is True
    assert result["archive_modified"] is False
    assert result["extracted_copy_only"] is True
    text = pth.read_text(encoding="utf-8")
    assert text.count("import site") == 1
    assert (guard / "sitecustomize.py").read_text(encoding="utf-8").startswith("from hl_observer.ops.portable_audit_guard")


def test_run_success_fatal_marker_and_timeout(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        portable.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="OK", stderr=""),
    )
    result = portable._run("ok", ["python", "-V"], cwd=tmp_path, env={}, timeout=1)
    assert result["ok"] is True and result["returncode"] == 0 and result["timed_out"] is False

    monkeypatch.setattr(
        portable.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="ModuleNotFoundError: x", stderr=""),
    )
    result = portable._run("fatal", ["x"], cwd=tmp_path, env={}, timeout=1)
    assert result["ok"] is False
    assert result["fatal_output_detected"] is True
    assert "modulenotfounderror:" in result["fatal_output_markers"]

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["x"], timeout=1)

    monkeypatch.setattr(portable.subprocess, "run", _timeout)
    result = portable._run("timeout", ["x"], cwd=tmp_path, env={}, timeout=1)
    assert result["returncode"] == 124 and result["timed_out"] is True and result["ok"] is False


def test_module_script_audit_log_and_short_root(tmp_path) -> None:
    script = portable._module_import_script(tmp_path)
    assert "importlib.import_module" in script
    assert "hl_observer" in script and "hyper_smart_observer" in script
    log = tmp_path / "audit.jsonl"
    assert portable._consume_audit_log(log) == []
    log.write_text("a\nb\n", encoding="utf-8")
    assert portable._consume_audit_log(log) == ["a", "b"]
    assert not log.exists()
    root = portable._short_execution_root()
    assert root.is_absolute()
    assert "hspv" in root.name.lower()


def test_ci_gate_github_actions_proof_file_and_fail_closed(tmp_path, monkeypatch) -> None:
    manifest = {"git_sha": "a" * 40}
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    row = portable._ci_gate(manifest)
    assert row["ok"] is True and row["provider"] == "github-actions-current-run"

    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    assert portable._ci_gate(manifest)["ok"] is False
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    proof = tmp_path / "proof.json"
    proof.write_text(json.dumps({
        "schema": portable.CI_SCHEMA,
        "provider": "github-actions",
        "conclusion": "success",
        "git_sha": "a" * 40,
        "run_id": "77",
    }), encoding="utf-8")
    assert portable._ci_gate(manifest, proof)["ok"] is True
    bad = json.loads(proof.read_text(encoding="utf-8"))
    bad["conclusion"] = "failure"
    proof.write_text(json.dumps(bad), encoding="utf-8")
    assert portable._ci_gate(manifest, proof)["ok"] is False
    assert portable._ci_gate(manifest)["ok"] is False
    assert portable._ci_gate(manifest, tmp_path / "missing.json")["ok"] is False


class _Response:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


def test_network_smoke_success_failure_optional_and_unsafe(monkeypatch) -> None:
    monkeypatch.setattr(portable, "NETWORK_ENDPOINTS", (
        ("required", "GET", "https://example.test/ok", None, True),
        ("optional", "GET", "https://example.test/fail", None, False),
        ("unsafe", "POST", "http://example.test/exchange", {"x": 1}, True),
    ))

    def opener(request, timeout):
        if request.full_url.endswith("/fail"):
            raise OSError("offline")
        return _Response(b'{"ok": true}', 200)

    row = portable.smoke_reseau_readonly(opener=opener, timeout=0.1)
    assert row["read_only"] is True
    assert row["credentials_sent"] is False
    assert row["exchange_endpoint_used"] is False
    assert row["ok"] is False  # unsafe required endpoint fails closed
    by_venue = {item["venue"]: item for item in row["results"]}
    assert by_venue["required"]["ok"] is True
    assert by_venue["optional"]["ok"] is False
    assert by_venue["unsafe"]["detail"] == "unsafe URL refused"

    monkeypatch.setattr(portable, "NETWORK_ENDPOINTS", (("required", "POST", "https://example.test/ok", {"type": "x"}, True),))
    row = portable.smoke_reseau_readonly(opener=lambda request, timeout: _Response(b'{"x": 1}', 204))
    assert row["ok"] is True
    assert row["results"][0]["method"] == "POST"


def test_main_success_and_failure_paths(tmp_path, monkeypatch, capsys) -> None:
    out = tmp_path / "result.json"
    monkeypatch.setattr(portable, "valider_archive_portable", lambda *a, **k: {"schema": portable.SCHEMA, "ok": True})
    assert portable.main(["--archive", "a.zip", "--output", str(out), "--pytest-timeout", "1"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is True

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(portable, "valider_archive_portable", _boom)
    assert portable.main(["--archive", "a.zip", "--output", str(out)]) == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is False and "RuntimeError" in payload["error"]
    assert "boom" in capsys.readouterr().out
