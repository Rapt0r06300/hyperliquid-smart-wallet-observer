from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "publish_local_recovery_snapshot_test",
        ROOT / "tools" / "publish_local_recovery_snapshot.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_local_snapshot_chunks_large_ignored_runtime_and_excludes_secrets(
    tmp_path, monkeypatch
):
    module = _module()
    project = tmp_path / "repo"
    runtime = project / "runtime" / "research_lab" / "continuous"
    runtime.mkdir(parents=True)
    (runtime / "episodes.jsonl").write_bytes(b"0123456789ABCDEFGHIJ")
    (project / "data").mkdir()
    (project / "data" / "result.json").write_text('{"pnl": 1}', encoding="utf-8")
    (project / "logs").mkdir()
    (project / "logs" / "secret-token.log").write_text("must-not-upload", encoding="utf-8")

    monkeypatch.setattr(module, "CHUNK_BYTES", 10)

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(module, "_gh", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr(module, "_ensure_release", lambda _repository, _tag: {})
    uploaded = {}

    def fake_upload(_repository, _tag, path):
        uploaded[path.name] = path.read_bytes()

    monkeypatch.setattr(module, "_upload_with_retry", fake_upload)

    result = module.publish_snapshot(
        project,
        "Rapt0r06300/hyperliquid-smart-wallet-observer",
        roots=("data", "logs", "runtime"),
        tag="alina-local-snapshot-test",
    )

    assert len(result["chunks"]) >= 3
    assert "ALINA_LOCAL_SNAPSHOT_INDEX.json" in uploaded
    paths = {row["path"] for row in result["files"]}
    assert "runtime/research_lab/continuous/episodes.jsonl" in paths
    assert "data/result.json" in paths
    assert "logs/secret-token.log" not in paths

    index = json.loads(uploaded["ALINA_LOCAL_SNAPSHOT_INDEX.json"])
    assert index["schema"] == "alina.local_snapshot.v1"
    assert index["excluded_secret_material"] is True


def test_discover_files_skips_recovery_recursion(tmp_path):
    module = _module()
    root = tmp_path / "repo"
    (root / "runtime" / "recovery").mkdir(parents=True)
    (root / "runtime" / "recovery" / "old.bin").write_bytes(b"old")
    (root / "runtime" / "replay").mkdir(parents=True)
    wanted = root / "runtime" / "replay" / "new.bin"
    wanted.write_bytes(b"new")

    files = module.discover_files(root, ("runtime",))

    assert wanted in files
    assert not any("recovery" in path.parts for path in files)


def test_chunk_writer_snapshots_only_prefix_visible_at_open(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "CHUNK_BYTES", 64)
    uploaded = {}

    monkeypatch.setattr(
        module,
        "_upload_with_retry",
        lambda _repository, _tag, path: uploaded.setdefault(path.name, path.read_bytes()),
    )

    writer = module.ChunkWriter(tmp_path, "owner/repo", "alina-local-snapshot-test")
    digest = hashlib.sha256()
    source = io.BytesIO(b"stable-prefix" + b"new-bytes-after-open")

    segments = writer.write_stream(source, digest, limit_bytes=len(b"stable-prefix"))
    writer.finish()

    assert b"".join(uploaded[name] for name in sorted(uploaded)) == b"stable-prefix"
    assert sum(segment["bytes"] for segment in segments) == len(b"stable-prefix")
    assert digest.hexdigest() == hashlib.sha256(b"stable-prefix").hexdigest()


def test_chunk_writer_resumes_matching_remote_chunk_without_upload(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "CHUNK_BYTES", 16)
    payload = b"0123456789abcdef"
    digest = hashlib.sha256(payload).hexdigest()
    remote_assets = {
        "ALINA_LOCAL_SNAPSHOT.chunk0000.bin": {
            "name": "ALINA_LOCAL_SNAPSHOT.chunk0000.bin",
            "size": len(payload),
            "digest": "sha256:" + digest,
        }
    }
    uploads = []
    monkeypatch.setattr(
        module,
        "_upload_with_retry",
        lambda *_args, **_kwargs: uploads.append("called"),
    )

    writer = module.ChunkWriter(
        tmp_path,
        "owner/repo",
        "alina-local-snapshot-test",
        remote_assets=remote_assets,
    )
    file_digest = hashlib.sha256()
    segments = writer.write_stream(
        io.BytesIO(payload),
        file_digest,
        limit_bytes=len(payload),
    )
    writer.finish()

    assert uploads == []
    assert writer.parts[0]["sha256"] == digest
    assert sum(row["bytes"] for row in segments) == len(payload)


def test_chunk_writer_refuses_mismatched_remote_chunk(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "CHUNK_BYTES", 16)
    payload = b"0123456789abcdef"
    remote_assets = {
        "ALINA_LOCAL_SNAPSHOT.chunk0000.bin": {
            "name": "ALINA_LOCAL_SNAPSHOT.chunk0000.bin",
            "size": len(payload),
            "digest": "sha256:" + ("0" * 64),
        }
    }
    writer = module.ChunkWriter(
        tmp_path,
        "owner/repo",
        "alina-local-snapshot-test",
        remote_assets=remote_assets,
    )
    try:
        writer.write_stream(
            io.BytesIO(payload),
            hashlib.sha256(),
            limit_bytes=len(payload),
        )
    except module.SnapshotError as exc:
        assert "existing remote bytes differ" in str(exc)
    else:
        raise AssertionError("resuming onto different remote bytes must fail closed")


def test_resume_tag_is_persisted_and_reused(tmp_path):
    module = _module()
    root = tmp_path / "repo"
    root.mkdir()

    first = module._load_or_create_resume_tag(root, "owner/repo")
    second = module._load_or_create_resume_tag(root, "owner/repo")

    assert first == second
    assert first.startswith("alina-local-snapshot-")
    state = json.loads(module._snapshot_state_path(root).read_text(encoding="utf-8"))
    assert state["tag"] == first
    assert state["repository"] == "owner/repo"


def test_resume_state_rejects_repository_mismatch(tmp_path):
    module = _module()
    root = tmp_path / "repo"
    state_path = module._snapshot_state_path(root)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schema": "alina.local_snapshot_state.v1",
                "repository": "other/repo",
                "tag": "alina-local-snapshot-test",
            }
        ),
        encoding="utf-8",
    )

    try:
        module._load_or_create_resume_tag(root, "owner/repo")
    except module.SnapshotError as exc:
        assert "another repository" in str(exc)
    else:
        raise AssertionError("resume state must never cross repositories")


def test_discover_files_includes_useful_git_ignored_evidence_outside_default_roots(
    tmp_path,
):
    module = _module()
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / ".gitignore").write_text(
        "*.db\n*.log\nportable_runtime/\n.env\n",
        encoding="utf-8",
    )
    useful_db = root / "local-results.db"
    useful_log = root / "collector-extra.log"
    useful_db.write_bytes(b"db-evidence")
    useful_log.write_text("collector evidence", encoding="utf-8")
    (root / ".env").write_text("SECRET=never-upload", encoding="utf-8")
    portable = root / "portable_runtime"
    portable.mkdir()
    (portable / "python.exe").write_bytes(b"reproducible-runtime")

    files = module.discover_files(root, ("data", "logs", "reports", "runtime"))
    relative = {path.relative_to(root).as_posix() for path in files}

    assert "local-results.db" in relative
    assert "collector-extra.log" in relative
    assert ".env" not in relative
    assert "portable_runtime/python.exe" not in relative
