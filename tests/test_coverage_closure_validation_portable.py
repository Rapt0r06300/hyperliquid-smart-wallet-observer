from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import hl_observer.ops.validation_portable as portable


def test_hash_json_write_evidence_and_audit_log(tmp_path) -> None:
    source = tmp_path / "x.bin"
    source.write_bytes(b"abc")
    digest, size = portable._sha256(source)
    assert digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert size == 3
    payload_path = tmp_path / "payload.json"
    payload_path.write_text('{"a": 1}', encoding="utf-8")
    assert portable._json(payload_path) == {"a": 1}
    out = portable.write_evidence(tmp_path / "nested" / "evidence.json", {"ok": True})
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is True
    log = tmp_path / "audit.jsonl"
    assert portable._consume_audit_log(log) == []
    log.write_text("a\nb\n", encoding="utf-8")
    assert portable._consume_audit_log(log) == ["a", "b"] and not log.exists()


def test_hermetic_environment_and_pytest_isolation(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SYSTEMROOT", raising=False)
    monkeypatch.delenv("WINDIR", raising=False)
    with pytest.raises(RuntimeError, match="SystemRoot/WINDIR absent"):
        portable._hermetic_environment(tmp_path, tmp_path / "guard")
    system = tmp_path / "Windows"
    monkeypatch.setenv("SYSTEMROOT", str(system))
    monkeypatch.setenv("WINDIR", str(system))
    env = portable._hermetic_environment(tmp_path, tmp_path / "guard")
    assert env["PIP_NO_INDEX"] == "1"
    assert env["HL_ENABLE_MAINNET_EXECUTION"] == "0"
    assert env["HL_ENABLE_TESTNET_EXECUTION"] == "0"
    assert Path(env["TEMP"]).is_dir() and Path(env["HOME"]).is_dir()
    isolated = portable._pytest_environment(env)
    assert "HYPERSMART_PORTABLE_AUDIT_ROOT" not in isolated
    assert "HYPERSMART_PORTABLE_AUDIT_LOG" not in isolated


def test_install_sitecustomize_and_run_paths(tmp_path, monkeypatch) -> None:
    root = tmp_path / "release"
    python_dir = root / "tools" / "python"
    guard = python_dir / "Lib" / "site-packages"
    python_dir.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="one embedded"):
        portable._install_sitecustomize(root, guard)
    pth = python_dir / "python311._pth"
    pth.write_text("python311.zip\nLib\\site-packages\nimport site\n", encoding="utf-8")
    result = portable._install_sitecustomize(root, guard)
    assert result["ok"] is True and result["archive_modified"] is False
    assert pth.read_text(encoding="utf-8").count("import site") == 1

    monkeypatch.setattr(
        portable.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="OK", stderr=""),
    )
    row = portable._run("ok", ["python", "-V"], cwd=tmp_path, env={}, timeout=1)
    assert row["ok"] is True and row["timed_out"] is False

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["x"], timeout=1)

    monkeypatch.setattr(portable.subprocess, "run", timeout)
    row = portable._run("timeout", ["x"], cwd=tmp_path, env={}, timeout=1)
    assert row["returncode"] == 124 and row["timed_out"] is True


def test_ci_gate_and_network_smoke(tmp_path, monkeypatch) -> None:
    manifest = {"git_sha": "a" * 40}
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    assert portable._ci_gate(manifest)["ok"] is True
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    assert portable._ci_gate(manifest)["ok"] is False
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    proof = tmp_path / "proof.json"
    proof.write_text(
        json.dumps({
            "schema": portable.CI_SCHEMA,
            "provider": "github-actions",
            "conclusion": "success",
            "git_sha": "a" * 40,
            "run_id": "77",
        }),
        encoding="utf-8",
    )
    assert portable._ci_gate(manifest, proof)["ok"] is True

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self, limit):
            return b'{"ok": true}'

    monkeypatch.setattr(
        portable,
        "NETWORK_ENDPOINTS",
        (("required", "GET", "https://example.test/ok", None, True),),
    )
    row = portable.smoke_reseau_readonly(opener=lambda request, timeout: Response(), timeout=0.1)
    assert row["ok"] is True and row["read_only"] is True
    assert row["credentials_sent"] is False and row["exchange_endpoint_used"] is False


def test_main_success_and_failure(tmp_path, monkeypatch) -> None:
    out = tmp_path / "result.json"
    monkeypatch.setattr(
        portable,
        "valider_archive_portable",
        lambda *args, **kwargs: {"schema": portable.SCHEMA, "ok": True},
    )
    assert portable.main(["--archive", "a.zip", "--output", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is True

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(portable, "valider_archive_portable", boom)
    assert portable.main(["--archive", "a.zip", "--output", str(out)]) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is False
