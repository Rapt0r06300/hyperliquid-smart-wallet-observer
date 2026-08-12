"""Portable validation, network allowlist and inherited audit-guard tests."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.ops import validation_portable as VP  # noqa: E402


@pytest.mark.skipif(os.name != "nt", reason="valide l'archive portable via l'environnement Windows (SystemRoot/WINDIR)")
def test_pytest_basetemp_is_isolated_from_runtime_cleanup(tmp_path):
    root = tmp_path / "release"
    guard = root / "tools" / "python" / "Lib" / "site-packages"

    env = VP._hermetic_environment(root, guard)

    workspace = root / VP.VALIDATION_WORKSPACE_NAME
    assert Path(env["TEMP"]).is_relative_to(workspace)
    assert Path(env["HYPERSMART_PORTABLE_AUDIT_LOG"]).is_relative_to(workspace)
    assert "runtime" not in Path(env["TEMP"]).relative_to(root).parts


def test_pytest_environment_does_not_change_product_guard(tmp_path):
    root = tmp_path / "release"
    guard = root / "tools" / "python" / "Lib" / "site-packages"
    product_env = VP._hermetic_environment(root, guard)

    pytest_env = VP._pytest_environment(product_env)

    assert "HYPERSMART_PORTABLE_AUDIT_ROOT" in product_env
    assert "HYPERSMART_PORTABLE_AUDIT_LOG" in product_env
    assert "HYPERSMART_PORTABLE_AUDIT_ROOT" not in pytest_env
    assert "HYPERSMART_PORTABLE_AUDIT_LOG" not in pytest_env
    assert pytest_env["PATH"] == product_env["PATH"]
    assert pytest_env["TEMP"] == product_env["TEMP"]
    assert pytest_env["PIP_NO_INDEX"] == "1"
    assert pytest_env["HL_ENABLE_MAINNET_EXECUTION"] == "0"
    assert pytest_env["HL_ENABLE_TESTNET_EXECUTION"] == "0"


class _Response:
    status = 200

    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self.payload


def test_network_smoke_uses_only_fixed_readonly_endpoints():
    requests = []

    def opener(request, timeout):
        requests.append((request.full_url, request.get_method(), request.data, timeout))
        return _Response(b'{"ok": true}')

    result = VP.smoke_reseau_readonly(opener=opener, timeout=1.0)
    assert result["ok"] is True
    assert result["credentials_sent"] is False
    assert result["exchange_endpoint_used"] is False
    assert len(requests) == 3
    assert all(url.startswith("https://") and "/exchange" not in url for url, *_ in requests)
    assert requests[0][2] == b'{"type": "allMids"}'
    assert requests[1][0].startswith("https://data-api.binance.vision/")
    assert requests[1][2] is None and requests[2][2] is None


def test_network_smoke_keeps_legacy_dydx_optional():
    def opener(request, timeout):
        del timeout
        if "dydx" in request.full_url:
            raise OSError("legacy venue unavailable")
        return _Response(b'{"ok": true}')

    result = VP.smoke_reseau_readonly(opener=opener, timeout=1.0)
    assert result["ok"] is True
    dydx = next(row for row in result["results"] if row["venue"] == "dydx")
    assert dydx["required"] is False
    assert dydx["ok"] is False


def test_network_smoke_fails_when_required_hyperliquid_is_unavailable():
    def opener(request, timeout):
        del timeout
        if "hyperliquid" in request.full_url:
            raise OSError("required venue unavailable")
        return _Response(b'{"ok": true}')

    assert VP.smoke_reseau_readonly(opener=opener, timeout=1.0)["ok"] is False


@pytest.mark.skipif(os.name != "nt", reason="embedded Windows Python executable")
def test_audit_guard_is_inherited_and_blocks_external_write(tmp_path):
    extracted = tmp_path / "extracted"
    extracted.mkdir(parents=True)
    log = extracted / "violations.jsonl"
    outside = tmp_path.parent / "portable-forbidden-write.txt"
    outside.unlink(missing_ok=True)
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(ROOT / "src"),
        "HYPERSMART_PORTABLE_AUDIT_ROOT": str(extracted),
        "HYPERSMART_PORTABLE_AUDIT_LOG": str(log),
        "PYTHONNOUSERSITE": "1",
    })
    completed = subprocess.run(
        [str(ROOT / "tools" / "python" / "python.exe"), "-c",
         "from hl_observer.ops.portable_audit_guard import install_from_environment; "
         "install_from_environment(); from pathlib import Path; "
         f"Path({str(outside)!r}).write_text('forbidden')"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert not outside.exists()
    assert "external write" in (completed.stderr + completed.stdout)
    assert log.is_file() and "open" in log.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="Windows null device")
def test_audit_guard_allows_windows_null_device(tmp_path):
    extracted = tmp_path / "extracted"
    extracted.mkdir(parents=True)
    log = extracted / "violations.jsonl"
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(ROOT / "src"),
        "HYPERSMART_PORTABLE_AUDIT_ROOT": str(extracted),
        "HYPERSMART_PORTABLE_AUDIT_LOG": str(log),
        "PYTHONNOUSERSITE": "1",
    })
    completed = subprocess.run(
        [str(ROOT / "tools" / "python" / "python.exe"), "-c",
         "from hl_observer.ops.portable_audit_guard import install_from_environment; "
         "install_from_environment(); "
         "open(r'\\\\.\\NUL', 'w').write('discarded'); print('NULL_DEVICE_OK')"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "NULL_DEVICE_OK" in completed.stdout
    assert not log.exists()


def test_run_rejects_fatal_python_output_even_with_zero_exit(tmp_path):
    result = VP._run(
        "masked-fatal",
        [sys.executable, "-c", "print('Fatal Python error: init_fs_encoding')"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout=30,
    )
    assert result["returncode"] == 0
    assert result["ok"] is False
    assert result["fatal_output_detected"] is True
    assert "fatal python error" in result["fatal_output_markers"]


def test_run_accepts_nonfatal_traceback_text_when_process_succeeds(tmp_path):
    result = VP._run(
        "benign-atexit",
        [sys.executable, "-c", "print('Traceback (most recent call last):\\ncleanup warning')"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout=30,
    )
    assert result["returncode"] == 0
    assert result["ok"] is True
    assert result["fatal_output_detected"] is False


def test_extracted_audit_bootstrap_is_local_and_enables_site(tmp_path):
    root = tmp_path / "release"
    python_dir = root / "tools" / "python"
    guard_dir = python_dir / "Lib" / "site-packages"
    python_dir.mkdir(parents=True)
    pth = python_dir / "python314._pth"
    pth.write_text(
        "python314.zip\n.\nLib\\site-packages\n..\\..\\src\n",
        encoding="utf-8",
    )

    evidence = VP._install_sitecustomize(root, guard_dir)

    assert evidence["ok"] is True
    assert evidence["extracted_copy_only"] is True
    assert pth.read_text(encoding="utf-8").splitlines()[-1] == "import site"
    assert "install_from_environment" in (guard_dir / "sitecustomize.py").read_text(
        encoding="utf-8"
    )


def _portable_fixture(path: Path) -> dict:
    files = {
        "tools/python/python.exe": b"MZ",
        "tools/python/python314._pth": (
            b"python314.zip\n.\nLib\\site-packages\n..\\..\\src\n"
        ),
        "src/hl_observer/__init__.py": b"",
    }
    manifest_files = {
        name: {"sha256": hashlib.sha256(data).hexdigest(), "taille": len(data)}
        for name, data in files.items()
    }
    digest = hashlib.sha256()
    for name in sorted(manifest_files):
        digest.update(name.encode("utf-8"))
        digest.update(manifest_files[name]["sha256"].encode("ascii"))
    manifest = {
        "schema": "hypersmart.portable_manifest.v1", "git_sha": "c" * 40,
        "empreinte_globale": digest.hexdigest(), "fichiers": manifest_files,
    }
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
        bundle.writestr("PORTABLE_MANIFEST.json", json.dumps(manifest))
    return manifest


@pytest.mark.skipif(os.name != "nt", reason="valide l'archive portable via l'environnement Windows (SystemRoot/WINDIR)")
def test_validation_evidence_is_bound_and_not_declarative(tmp_path, monkeypatch):
    archive = tmp_path / "release.zip"
    manifest = _portable_fixture(archive)
    repeated = tmp_path / "release-repeat.zip"
    shutil.copy2(archive, repeated)
    proof = tmp_path / "ci.json"
    proof.write_text(json.dumps({
        "schema": VP.CI_SCHEMA, "provider": "github-actions", "conclusion": "success",
        "git_sha": manifest["git_sha"], "run_id": "123",
    }), encoding="utf-8")

    def fake_run(name, command, *, cwd, env, timeout):
        if name == "pytest_full":
            assert "HYPERSMART_PORTABLE_AUDIT_ROOT" not in env
            assert "HYPERSMART_PORTABLE_AUDIT_LOG" not in env
        if name == "analyser":
            report = cwd / "runtime" / "reports" / "backtest_replay" / "RAPPORT_PORTABLE_SMOKE.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({
                "ledger_reconciliation": {"ok": True},
                "session_closure": {"statut": "COMPLETE"},
            }), encoding="utf-8")
        stdout = "PORTABLE_LAUNCHER_CHECK_OK" if name == "launcher" else "OK"
        return {"name": name, "ok": True, "returncode": 0, "timed_out": False,
                "duration_seconds": 0.01, "command": list(command),
                "stdout_tail": stdout, "stderr_tail": ""}

    monkeypatch.setattr(VP, "_run", fake_run)
    monkeypatch.setattr(VP, "_processes_for_root", lambda _root: set())
    monkeypatch.setattr(VP, "smoke_reseau_readonly", lambda **_kwargs: {"ok": True})
    execution_root = tmp_path / "hspv éà execution"
    monkeypatch.setattr(VP, "_short_execution_root", lambda: execution_root)
    result = VP.valider_archive_portable(
        archive, archive_repetition=repeated, ci_proof=proof,
        extraction_parent=tmp_path / "extracts",
    )
    assert result["ok"] is True
    assert result["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert result["manifest_fingerprint"] == manifest["empreinte_globale"]
    assert result["checks"]["build_reproductible"]["ok"] is True
    assert result["checks"]["analyseur_backtests"]["ledger_reconciled"] is True
    pytest_command = next(row for row in result["commands"] if row["name"] == "pytest_full")
    assert "--timeout=120" in pytest_command["command"]
    assert "--timeout-method=thread" in pytest_command["command"]
    assert pytest_command["product_audit_guard_applied"] is False
    assert pytest_command["workspace_isolated"] is True
    assert result["checks"]["zero_ecriture_externe"]["ok"] is True
    simple = tmp_path / "extracts" / "simple" / "tools" / "python"
    assert "import site" not in (simple / "python314._pth").read_text(encoding="utf-8")
    assert not (simple / "Lib" / "site-packages" / "sitecustomize.py").exists()
    assert result["checks"]["audit_bootstrap"]["extracted_copy_only"] is True
