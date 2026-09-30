from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import hl_observer.ops.validation_portable as portable


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit: int) -> bytes:
        del limit
        return b'{"ok": true, "serverTime": 1}'


def _successful_run(name: str, command, *, cwd: Path, env, timeout: int):
    del command, env, timeout
    if name == "analyser":
        report = cwd / "runtime" / "reports" / "backtest_replay" / "RAPPORT_PORTABLE_SMOKE.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(
                {
                    "ledger_reconciliation": {"ok": True},
                    "session_closure": {"statut": "COMPLETE"},
                }
            ),
            encoding="utf-8",
        )
    stdout = "PORTABLE_LAUNCHER_CHECK_OK" if name == "launcher" else "OK"
    return {
        "name": name,
        "ok": True,
        "returncode": 0,
        "timed_out": False,
        "fatal_output_detected": False,
        "fatal_output_markers": [],
        "duration_seconds": 0.0,
        "command": [],
        "stdout_tail": stdout,
        "stderr_tail": "",
    }


def test_valider_archive_portable_traverse_full_orchestration(tmp_path, monkeypatch) -> None:
    archive = tmp_path / "portable.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(portable.NOM_MANIFESTE, json.dumps({"git_sha": "unit-sha"}))
        bundle.writestr("sample.txt", "unit")
    repetition = tmp_path / "portable-repeat.zip"
    repetition.write_bytes(archive.read_bytes())

    primary = tmp_path / "short primary éà"
    parent = tmp_path / "extractions"
    parent.mkdir()

    def fake_extract(_bundle, destination: Path):
        destination.mkdir(parents=True, exist_ok=True)
        python = destination / "tools" / "python" / "python.exe"
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_bytes(b"MZ")
        return {"ok": True, "destination": str(destination)}

    monkeypatch.setattr(portable, "extraire_zip_surement", fake_extract)
    monkeypatch.setattr(
        portable,
        "extraire_et_reverifier",
        lambda *_args, **_kwargs: {"ok": True, "verified": True},
    )
    monkeypatch.setattr(portable, "_short_execution_root", lambda: primary)
    monkeypatch.setattr(
        portable,
        "_install_sitecustomize",
        lambda root, guard: {
            "ok": True,
            "pth": "tools/python/python311._pth",
            "sitecustomize": "tools/python/Lib/site-packages/sitecustomize.py",
            "archive_modified": False,
            "extracted_copy_only": True,
        },
    )

    def fake_environment(root: Path, guard: Path):
        del guard
        workspace = root / portable.VALIDATION_WORKSPACE_NAME
        workspace.mkdir(parents=True, exist_ok=True)
        return {
            "HYPERSMART_PORTABLE_AUDIT_LOG": str(workspace / "audit.jsonl"),
            "COMSPEC": "cmd.exe",
            "PYTHONNOUSERSITE": "1",
            "PIP_NO_INDEX": "1",
        }

    monkeypatch.setattr(portable, "_hermetic_environment", fake_environment)
    monkeypatch.setattr(portable, "_run", _successful_run)
    monkeypatch.setattr(portable, "_process_scanner_available", lambda: True)
    process_snapshots = iter(({101}, {101}))
    monkeypatch.setattr(portable, "_processes_for_root", lambda _root: next(process_snapshots))
    monkeypatch.setattr(portable.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        portable,
        "_ci_gate",
        lambda manifest, proof=None: {
            "ok": True,
            "provider": "unit",
            "git_sha": manifest.get("git_sha"),
            "proof": str(proof or ""),
        },
    )

    result = portable.valider_archive_portable(
        archive,
        archive_repetition=repetition,
        ci_proof=tmp_path / "ci.json",
        network_opener=lambda request, timeout: _Response(),
        extraction_parent=parent,
        pytest_timeout=1,
    )

    assert result["schema"] == portable.SCHEMA
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
    assert result["checks"]["hashes_extraits"]["ok"] is True
    assert result["checks"]["lanceur_hypersmart"]["success_marker_seen"] is True
    assert result["checks"]["analyseur_backtests"]["ledger_reconciled"] is True
    assert result["checks"]["analyseur_backtests"]["session_complete"] is True
    assert result["checks"]["smoke_reseau_readonly"]["ok"] is True
    assert result["checks"]["zero_processus_orphelin"]["ok"] is True
    assert result["checks"]["build_reproductible"]["ok"] is True
    # Linux CI correctly keeps this Windows-only witness false; the goal here
    # is to execute the real orchestration without pretending a Windows proof.
    assert result["checks"]["test_hermetique_windows"]["ok"] is (os.name == "nt")


def test_validation_portable_small_remaining_platform_branches(tmp_path, monkeypatch) -> None:
    # Manifest helper.
    archive = tmp_path / "manifest.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(portable.NOM_MANIFESTE, '{"git_sha":"abc"}')
    assert portable._manifest_from_archive(archive)["git_sha"] == "abc"

    # Process scanner success path and missing-psutil fallback are already
    # exercised elsewhere; here use a deterministic fake process iterator to
    # cover matching, ignored and disappeared processes.
    class _NoSuchProcess(Exception):
        pass

    class _AccessDenied(Exception):
        pass

    class _Proc:
        def __init__(self, pid, cmdline=None, error=None):
            self.info = {"pid": pid, "cmdline": cmdline}
            self.error = error

    fake_psutil = SimpleNamespace(
        AccessDenied=_AccessDenied,
        NoSuchProcess=_NoSuchProcess,
        process_iter=lambda _fields: [
            _Proc(10, ["python", str(tmp_path), "worker"]),
            _Proc(11, ["python", "elsewhere"]),
        ],
    )
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)
    assert portable._processes_for_root(tmp_path) == {10}
    assert portable._process_scanner_available() is True

    log = tmp_path / "audit.jsonl"
    log.write_text("one\ntwo\n", encoding="utf-8")
    assert portable._consume_audit_log(log) == ["one", "two"]
    assert portable._consume_audit_log(log) == []

    root = portable._short_execution_root()
    assert root.is_absolute()
