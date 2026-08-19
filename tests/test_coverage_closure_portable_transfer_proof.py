from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import hl_observer.ops.portable_transfer_proof as proof


def _manifest(root: Path, source: str = "pc-a") -> None:
    (root / "PORTABLE_FULL_CLONE_MANIFEST.json").write_text(
        json.dumps({"source_machine_fingerprint": source}),
        encoding="utf-8",
    )


def _make_required_assets(root: Path) -> None:
    for relative in proof.REQUIRED_POST_TRANSFER_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    wheel = root / "tools" / "wheelhouse" / "a.whl"
    wheel.parent.mkdir(parents=True, exist_ok=True)
    wheel.write_bytes(b"w")
    dll = root / "tools" / "python" / "a.dll"
    dll.parent.mkdir(parents=True, exist_ok=True)
    dll.write_bytes(b"d")
    ca = root / "tools" / "python" / "Lib" / "site-packages" / "certifi" / "cacert.pem"
    ca.parent.mkdir(parents=True, exist_ok=True)
    ca.write_text("ca", encoding="utf-8")


def test_run_latest_session_and_health(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        proof.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    row = proof._run(["x"], cwd=tmp_path, timeout=1, env={})
    assert row["ok"] is True and row["stdout_tail"] == "ok"

    sessions = tmp_path / "runtime" / "data" / "sessions" / "complete"
    sessions.mkdir(parents=True)
    catalog = sessions / "DATA_CATALOG.json"
    catalog.write_text('{"run_id":"run-1","status":"complete"}', encoding="utf-8")
    cutoff = time.time() - 1
    result = proof._latest_complete_session(tmp_path, not_before=cutoff)
    assert result["ok"] is True and result["run_id"] == "run-1"

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    monkeypatch.setattr(proof.urllib.request, "urlopen", lambda url, timeout: Response())
    assert proof._health_ok("http://127.0.0.1") is True
    monkeypatch.setattr(
        proof.urllib.request,
        "urlopen",
        lambda url, timeout: (_ for _ in ()).throw(OSError("offline")),
    )
    assert proof._health_ok("bad") is False


def test_post_transfer_assets_missing_and_success(tmp_path) -> None:
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return {"ok": True}

    missing = proof._post_transfer_assets(tmp_path, runner=runner, env={})
    assert missing["ok"] is False and missing["missing"]
    _make_required_assets(tmp_path)
    result = proof._post_transfer_assets(tmp_path, runner=runner, env={})
    assert result["ok"] is True
    assert result["wheel_count"] == 1 and result["dll_count"] == 1
    assert result["tls_ca_files"]


def test_prove_transferred_clone_fail_closed_and_success(tmp_path) -> None:
    assert proof.prove_transferred_clone(tmp_path)["reason"].startswith("manifest_invalid:")
    _manifest(tmp_path, source="")
    assert proof.prove_transferred_clone(
        tmp_path,
        current_fingerprint=lambda: "pc-b",
    )["reason"] == "source_machine_proof_missing"
    _manifest(tmp_path, source="pc-a")
    assert proof.prove_transferred_clone(
        tmp_path,
        current_fingerprint=lambda: "pc-a",
    )["reason"] == "physical_pc_b_required"

    base = {
        "current_fingerprint": lambda: "pc-b",
        "clone_verifier": lambda root, full_hash: {"ok": True},
        "asset_verifier": lambda *args, **kwargs: {"ok": True},
    }

    def runner(command, **kwargs):
        return {"ok": True, "returncode": 0}

    row = proof.prove_transferred_clone(
        tmp_path,
        collection_seconds=899,
        runner=runner,
        collection_runner=lambda root, seconds, env: {"ok": True},
        **base,
    )
    assert row["reason"] == "collection_below_900_seconds"

    row = proof.prove_transferred_clone(
        tmp_path,
        collection_seconds=900,
        runner=runner,
        collection_runner=lambda root, seconds, env: {"ok": True, "health_ratio": 1.0},
        **base,
    )
    assert row["ok"] is True and row["portable_ready"] is True
    assert row["reason"] == "pc_a_to_pc_b_full_proof_passed"
    assert [step["name"] for step in row["steps"]][-3:] == [
        "collection_15_minutes_and_clean_stop",
        "replay_full",
        "replay_deep",
    ]


def test_stop_spawned_launcher_timeout_fallback(tmp_path, monkeypatch) -> None:
    class Process:
        def __init__(self) -> None:
            self.calls = 0
            self.stdin = SimpleNamespace(
                write=lambda value: None,
                flush=lambda: None,
                close=lambda: None,
            )
        def poll(self):
            return None if self.calls == 0 else 0
        def wait(self, timeout):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("x", timeout)
            return 0
        def terminate(self):
            self.calls += 1

    stop_calls = []
    monkeypatch.setattr(
        proof.subprocess,
        "run",
        lambda *args, **kwargs: stop_calls.append(args[0]) or SimpleNamespace(returncode=0),
    )
    process = Process()
    proof._stop_spawned_launcher(tmp_path, process, {})
    assert stop_calls and stop_calls[0][-1] == "stop"
