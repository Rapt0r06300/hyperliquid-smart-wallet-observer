from __future__ import annotations

import io
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import hl_observer.ops.portable_transfer_proof as proof


def test_run_success_and_exception(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        proof.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    result = proof._run(["x"], cwd=tmp_path, timeout=1, env={})
    assert result["ok"] is True and result["returncode"] == 0
    assert result["stdout_tail"] == "ok"

    monkeypatch.setattr(
        proof.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")),
    )
    result = proof._run(["x"], cwd=tmp_path, timeout=1, env={})
    assert result["ok"] is False and result["returncode"] == -1 and "boom" in result["stderr_tail"]


def test_latest_complete_session_filters_bad_old_and_incomplete(tmp_path) -> None:
    sessions = tmp_path / "runtime" / "data" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "bad").mkdir()
    (sessions / "bad" / "DATA_CATALOG.json").write_text("bad", encoding="utf-8")
    (sessions / "active").mkdir()
    (sessions / "active" / "DATA_CATALOG.json").write_text('{"run_id":"active","statut":"ACTIVE"}', encoding="utf-8")
    cutoff = time.time()
    assert proof._latest_complete_session(tmp_path, not_before=cutoff)["reason"] == "no_fresh_complete_session"

    complete = sessions / "complete"
    complete.mkdir()
    catalog = complete / "DATA_CATALOG.json"
    catalog.write_text('{"run_id":"run-1","status":"complete"}', encoding="utf-8")
    now = time.time() + 1
    import os
    os.utime(catalog, (now, now))
    result = proof._latest_complete_session(tmp_path, not_before=cutoff)
    assert result["ok"] is True and result["run_id"] == "run-1" and result["status"] == "COMPLETE"


def test_health_ok_success_and_fail(monkeypatch) -> None:
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr(proof.urllib.request, "urlopen", lambda url, timeout: Response())
    assert proof._health_ok("http://127.0.0.1") is True
    monkeypatch.setattr(proof.urllib.request, "urlopen", lambda url, timeout: (_ for _ in ()).throw(OSError("offline")))
    assert proof._health_ok("bad") is False


class _FakeProcess:
    def __init__(self, *, alive=True, wait_timeout=False):
        self.alive = alive
        self.returncode = None if alive else 0
        self.stdin = SimpleNamespace(
            write=lambda value: None,
            flush=lambda: None,
            close=lambda: None,
        )
        self.wait_timeout = wait_timeout
        self.terminated = False

    def poll(self):
        return None if self.alive else self.returncode

    def wait(self, timeout):
        if self.wait_timeout:
            self.wait_timeout = False
            raise subprocess.TimeoutExpired("x", timeout)
        self.alive = False
        self.returncode = 0
        return 0

    def terminate(self):
        self.terminated = True
        self.alive = False
        self.returncode = -15


def test_stop_spawned_launcher_already_stopped_clean_and_fallback(tmp_path, monkeypatch) -> None:
    stopped = _FakeProcess(alive=False)
    proof._stop_spawned_launcher(tmp_path, stopped, {})

    clean = _FakeProcess(alive=True)
    proof._stop_spawned_launcher(tmp_path, clean, {})
    assert clean.poll() == 0

    fallback = _FakeProcess(alive=True, wait_timeout=True)
    calls = []
    monkeypatch.setattr(proof.subprocess, "run", lambda *a, **k: calls.append(a[0]) or SimpleNamespace(returncode=0))
    proof._stop_spawned_launcher(tmp_path, fallback, {})
    assert calls and calls[0][-1] == "stop"
    assert fallback.poll() is not None


def _make_required_assets(root: Path) -> None:
    for relative in proof.REQUIRED_POST_TRANSFER_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    whl = root / "tools" / "wheelhouse" / "a.whl"
    whl.parent.mkdir(parents=True, exist_ok=True); whl.write_bytes(b"w")
    dll = root / "tools" / "python" / "a.dll"
    dll.parent.mkdir(parents=True, exist_ok=True); dll.write_bytes(b"d")
    ca = root / "tools" / "python" / "Lib" / "site-packages" / "certifi" / "cacert.pem"
    ca.parent.mkdir(parents=True, exist_ok=True); ca.write_text("ca", encoding="utf-8")


def test_post_transfer_assets_missing_and_success(tmp_path) -> None:
    calls = []
    runner = lambda command, **kwargs: (calls.append(command) or {"ok": True})
    missing = proof._post_transfer_assets(tmp_path, runner=runner, env={})
    assert missing["ok"] is False and missing["missing"]
    assert missing["dynamic_imports"]["ok"] is False

    _make_required_assets(tmp_path)
    result = proof._post_transfer_assets(tmp_path, runner=runner, env={})
    assert result["ok"] is True
    assert result["wheel_count"] == 1 and result["dll_count"] == 1
    assert len(result["tls_ca_files"]) == 1
    assert len(calls) >= 2


def _manifest(root: Path, source="pc-a") -> None:
    (root / "PORTABLE_FULL_CLONE_MANIFEST.json").write_text(
        json.dumps({"source_machine_fingerprint": source}), encoding="utf-8"
    )


def test_prove_transferred_clone_manifest_machine_hash_and_assets_failures(tmp_path) -> None:
    assert proof.prove_transferred_clone(tmp_path)["reason"].startswith("manifest_invalid:")
    _manifest(tmp_path, source="")
    assert proof.prove_transferred_clone(tmp_path, current_fingerprint=lambda: "pc-b")["reason"] == "source_machine_proof_missing"
    _manifest(tmp_path, source="pc-a")
    assert proof.prove_transferred_clone(tmp_path, current_fingerprint=lambda: "pc-a")["reason"] == "physical_pc_b_required"

    result = proof.prove_transferred_clone(
        tmp_path,
        current_fingerprint=lambda: "pc-b",
        clone_verifier=lambda root, full_hash: {"ok": False},
    )
    assert result["reason"] == "full_hash_verification_failed"

    result = proof.prove_transferred_clone(
        tmp_path,
        current_fingerprint=lambda: "pc-b",
        clone_verifier=lambda root, full_hash: {"ok": True},
        asset_verifier=lambda *a, **k: {"ok": False},
    )
    assert result["reason"] == "post_transfer_assets_failed"


def test_prove_transferred_clone_command_fail_collection_fail_short_and_replays(tmp_path) -> None:
    _manifest(tmp_path)
    _make_required_assets(tmp_path)
    base = dict(
        current_fingerprint=lambda: "pc-b",
        clone_verifier=lambda root, full_hash: {"ok": True},
        asset_verifier=lambda *a, **k: {"ok": True},
    )
    calls = []
    def fail_first(command, **kwargs):
        calls.append(command)
        return {"ok": False}
    result = proof.prove_transferred_clone(tmp_path, runner=fail_first, collection_seconds=900, **base)
    assert result["reason"] == "portable_check_failed" and len(result["steps"]) == 1

    runner = lambda command, **kwargs: {"ok": True, "command": list(command)}
    result = proof.prove_transferred_clone(
        tmp_path, runner=runner,
        collection_runner=lambda root, seconds, env: {"ok": False},
        collection_seconds=900, **base,
    )
    assert result["reason"] == "collection_proof_failed"

    result = proof.prove_transferred_clone(
        tmp_path, runner=runner,
        collection_runner=lambda root, seconds, env: {"ok": True},
        collection_seconds=899, **base,
    )
    assert result["reason"] == "collection_below_900_seconds"

    replay_count = {"n": 0}
    def replay_runner(command, **kwargs):
        if command[-1] in {"full", "deep"}:
            replay_count["n"] += 1
            if command[-1] == "deep":
                return {"ok": False}
        return {"ok": True}
    result = proof.prove_transferred_clone(
        tmp_path, runner=replay_runner,
        collection_runner=lambda root, seconds, env: {"ok": True},
        collection_seconds=900, **base,
    )
    assert result["reason"] == "replay_deep_failed"
    assert replay_count["n"] == 2


def test_prove_transferred_clone_full_success(tmp_path) -> None:
    _manifest(tmp_path)
    _make_required_assets(tmp_path)
    calls = []
    def runner(command, **kwargs):
        calls.append(list(command))
        return {"ok": True, "returncode": 0}
    result = proof.prove_transferred_clone(
        tmp_path,
        collection_seconds=900,
        runner=runner,
        collection_runner=lambda root, seconds, env: {"ok": True, "health_ratio": 1.0},
        asset_verifier=lambda *a, **k: {"ok": True},
        clone_verifier=lambda root, full_hash: {"ok": True, "full_hash": full_hash},
        current_fingerprint=lambda: "pc-b",
    )
    assert result["ok"] is True and result["portable_ready"] is True
    assert result["reason"] == "pc_a_to_pc_b_full_proof_passed"
    assert result["source_machine_fingerprint"] == "pc-a"
    assert result["target_machine_fingerprint"] == "pc-b"
    assert result["collection_seconds"] == 900
    assert [step["name"] for step in result["steps"]][-3:] == [
        "collection_15_minutes_and_clean_stop", "replay_full", "replay_deep"
    ]
    assert len(calls) == 6


def test_write_report_and_main_success_failure(tmp_path, monkeypatch, capsys) -> None:
    path = proof._write_report(tmp_path, {"portable_ready": True})
    assert path == tmp_path / proof.REPORT_RELATIVE
    assert json.loads(path.read_text(encoding="utf-8"))["portable_ready"] is True

    monkeypatch.setattr(proof, "prove_transferred_clone", lambda root, collection_seconds: {"ok": True, "portable_ready": True})
    assert proof.main(["--root", str(tmp_path), "--collection-seconds", "900"]) == 0
    assert '"portable_ready": true' in capsys.readouterr().out.lower()

    monkeypatch.setattr(proof, "prove_transferred_clone", lambda root, collection_seconds: {"ok": False, "portable_ready": False})
    assert proof.main(["--root", str(tmp_path)]) == 6
