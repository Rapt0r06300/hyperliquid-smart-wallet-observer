from __future__ import annotations

import importlib.util
import json
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
