from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import hl_observer.ops.portable_clone as clone
from hl_observer.ops.portable_clone_inventory import CloneInventory, PlannedFile, PortableCloneError


def _inv(*files: PlannedFile) -> CloneInventory:
    return CloneInventory(
        files=tuple(files),
        excluded=({"path": "tmp", "reason": "transient"},),
        total_bytes=sum(row.size for row in files),
        sqlite_count=sum(row.kind == "sqlite" for row in files),
        longest_relative_path=max((len(row.relative_path) for row in files), default=0),
        longest_relative_member=max((files or (PlannedFile("", 0, "file"),)), key=lambda row: len(row.relative_path)).relative_path,
    )


def test_hash_and_copy_helpers(tmp_path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"abcdef")
    destination = tmp_path / "nested" / "copy.bin"
    digest, size = clone._copy_and_hash(source, destination, buffer_size=2)
    assert size == 6
    assert digest == hashlib.sha256(b"abcdef").hexdigest()
    assert destination.read_bytes() == b"abcdef"
    digest2, size2 = clone._hash_file(destination, buffer_size=3)
    assert (digest2, size2) == (digest, size)


def test_automatic_destination_selects_space_and_fails_closed(tmp_path, monkeypatch) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir(); b.mkdir()
    monkeypatch.setattr(clone, "_available_drive_roots", lambda: [a, b])

    def usage(path):
        if path == a:
            return SimpleNamespace(free=100)
        return SimpleNamespace(free=2_000_000_000)

    monkeypatch.setattr(clone.shutil, "disk_usage", usage)
    result = clone.automatic_destination(100, now=0.1)
    assert result.parent == b
    assert result.name.startswith("HS_PORTABLE_")

    monkeypatch.setattr(clone.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    with pytest.raises(PortableCloneError, match="no drive has enough free space"):
        clone.automatic_destination(10_000)


def test_validate_destination_overlap_existing_long_and_disk(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    inv = _inv(PlannedFile("x", 10, "file"))
    with pytest.raises(PortableCloneError, match="outside and separate"):
        clone._validate_destination(source, source / "child", inv)

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(PortableCloneError, match="already exists"):
        clone._validate_destination(source, existing, inv)

    long_inv = CloneInventory(files=(), excluded=(), total_bytes=0, sqlite_count=0, longest_relative_path=400, longest_relative_member="x")
    with pytest.raises(PortableCloneError, match="too long"):
        clone._validate_destination(source, tmp_path / "dest", long_inv)

    monkeypatch.setattr(clone.shutil, "disk_usage", lambda parent: SimpleNamespace(free=1))
    with pytest.raises(PortableCloneError, match="not enough free space"):
        clone._validate_destination(source, tmp_path / "dest2", inv)

    monkeypatch.setattr(clone.shutil, "disk_usage", lambda parent: SimpleNamespace(free=10**10))
    clone._validate_destination(source, tmp_path / "dest3", inv)
    assert (tmp_path).is_dir()


def test_verify_git_repository_success_and_failures(tmp_path, monkeypatch) -> None:
    embedded = tmp_path / "tools" / "git" / "cmd" / "git.exe"
    embedded.parent.mkdir(parents=True)
    embedded.write_text("fake", encoding="utf-8")
    outputs = {
        ("fsck", "--full"): SimpleNamespace(returncode=0, stdout="ok\n", stderr=""),
        ("rev-parse", "HEAD"): SimpleNamespace(returncode=0, stdout="a" * 40 + "\n", stderr=""),
        ("branch", "--show-current"): SimpleNamespace(returncode=0, stdout="main\n", stderr=""),
        ("remote", "-v"): SimpleNamespace(returncode=0, stdout="origin url (fetch)\n", stderr=""),
    }
    monkeypatch.setattr(clone, "_git_command", lambda root, *args, timeout=0: outputs[tuple(args)])
    result = clone.verify_git_repository(tmp_path)
    assert result["ok"] is True
    assert result["head"] == "a" * 40 and result["branch"] == "main"

    outputs[("branch", "--show-current")] = SimpleNamespace(returncode=0, stdout="dev\n", stderr="")
    result = clone.verify_git_repository(tmp_path)
    assert result["ok"] is False and "branch" in result["failures"]

    def raising(root, *args, timeout=0):
        if args[0] == "fsck":
            raise PortableCloneError("no git")
        return outputs[tuple(args)]

    monkeypatch.setattr(clone, "_git_command", raising)
    assert "fsck" in clone.verify_git_repository(tmp_path)["failures"]


def test_active_mutators_source_guard_and_source_state(tmp_path, monkeypatch) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    lock = root / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    findings = clone._active_project_mutators(root)
    assert "git-lock:.git/index.lock" in findings
    lock.unlink()

    monkeypatch.setattr(clone, "_active_project_mutators", lambda root: ["process:git:1"])
    with pytest.raises(PortableCloneError, match="active Git/Codex"):
        clone.source_worktree_guard(root)

    monkeypatch.setattr(clone, "_active_project_mutators", lambda root: [])
    calls = []

    def git_cmd(root, *args, timeout=120):
        calls.append(args)
        if args[0] == "status":
            return SimpleNamespace(returncode=0, stdout=" M dirty.py\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="x\n", stderr="")

    monkeypatch.setattr(clone, "_git_command", git_cmd)
    with pytest.raises(PortableCloneError, match="clean worktree"):
        clone.source_worktree_guard(root)

    def clean_git(root, *args, timeout=120):
        if args[0] == "status": return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[0] == "rev-parse": return SimpleNamespace(returncode=0, stdout="a" * 40 + "\n", stderr="")
        if args[0] == "branch": return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(clone, "_git_command", clean_git)
    result = clone.source_worktree_guard(root)
    assert result["head"] == "a" * 40 and result["branch"] == "main" and result["status"] == []

    f = root / "a.txt"
    f.write_text("abc", encoding="utf-8")
    inv = _inv(PlannedFile("a.txt", 3, "file"))
    state = clone._source_file_state(root, inv)
    assert state["a.txt"][0] == 3
    assert clone._inventory_signature(inv) == (("a.txt", 3, "file"),)
    f.unlink()
    with pytest.raises(PortableCloneError, match="source changed or disappeared"):
        clone._source_file_state(root, inv)


def _required_files(root: Path) -> list[str]:
    required = [
        "LANCER_HYPERSMART.cmd",
        "ANALYSER_BACKTESTS_REPLAYS.cmd",
        "POUSSER-GITHUB-FORCE.cmd",
        "CREER_ARCHIVE_PORTABLE.cmd",
        "tools/python/python.exe",
        "tools/portable_env.cmd",
        "tools/git/cmd/git.exe",
        "tools/push_github_safe.ps1",
        "src/hl_observer/__init__.py",
        "src/hl_observer/ops/portable_smoke.py",
    ]
    for rel in required:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    return required


def test_verify_clone_missing_invalid_success_and_divergence(tmp_path, monkeypatch) -> None:
    root = tmp_path / "clone"
    root.mkdir()
    assert clone.verify_clone(root)["reason"] == "manifest_missing"
    manifest_path = root / clone.MANIFEST_NAME
    manifest_path.write_text("not json", encoding="utf-8")
    assert clone.verify_clone(root)["reason"].startswith("manifest_invalid:")

    required = _required_files(root)
    empty_sha = hashlib.sha256(b"").hexdigest()
    files = {rel: {"size": 0, "sha256": empty_sha, "kind": "file"} for rel in required}
    source_git = {"head": "a" * 40, "branch": "main", "remotes": ["origin url (fetch)"]}
    manifest = {
        "schema_version": 2,
        "files": files,
        "durable_artifacts": clone._durable_artifact_summary(files),
        "source_git": source_git,
        "source_machine_fingerprint": "source-machine",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(clone, "machine_fingerprint", lambda: "current-machine")
    git = {"ok": True, **source_git, "fsck": ""}
    result = clone.verify_clone(root, git_verifier=lambda root: dict(git))
    assert result["ok"] is True
    assert result["verified"] == len(required)
    assert result["physical_machine_distinct"] is True
    assert result["git_identity_matches_source"] is True
    assert result["durable_artifacts_match_manifest"] is True

    (root / required[0]).write_bytes(b"x")
    result = clone.verify_clone(root, git_verifier=lambda root: dict(git))
    assert result["ok"] is False and required[0] in result["divergent"]

    (root / required[0]).write_bytes(b"")
    extra = root / "unexpected.txt"
    extra.write_text("x", encoding="utf-8")
    result = clone.verify_clone(root, full_hash=False, git_verifier=lambda root: dict(git))
    assert result["ok"] is False and "unexpected.txt" in result["unexpected"]


def test_create_full_clone_guards_and_success(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("abc", encoding="utf-8")
    (source / "db.sqlite").write_bytes(b"db")
    inv = _inv(PlannedFile("a.txt", 3, "file"), PlannedFile("db.sqlite", 2, "sqlite"))

    with pytest.raises(PortableCloneError, match="writers are still active"):
        clone.create_full_clone(source, tmp_path / "out", writer_probe=lambda root: ["w"], session_probe=lambda root: [])
    with pytest.raises(PortableCloneError, match="active sessions"):
        clone.create_full_clone(source, tmp_path / "out", writer_probe=lambda root: [], session_probe=lambda root: ["s"])

    monkeypatch.setattr(clone, "inventory", lambda root, **kwargs: inv)
    monkeypatch.setattr(clone, "_validate_destination", lambda source, dest, inventory: None)
    monkeypatch.setattr(clone, "machine_fingerprint", lambda: "machine")

    def sqlite_copy(src, dst):
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        return {"ok": True, "method": "backup"}

    monkeypatch.setattr(clone.AP, "copier_sqlite_vers_staging", sqlite_copy)
    monkeypatch.setattr(clone, "verify_clone", lambda root, **kwargs: {"ok": True, "root": str(root)})
    guard = {"head": "a" * 40, "branch": "main", "status": [], "active_mutators": []}
    git = {"ok": True, "head": "a" * 40, "branch": "main", "remotes": ["origin"]}
    progress = []
    out = tmp_path / "out"
    result = clone.create_full_clone(
        source,
        out,
        writer_probe=lambda root: [],
        session_probe=lambda root: [],
        worktree_guard=lambda root: dict(guard),
        git_verifier=lambda root: dict(git),
        progress=progress.append,
    )
    assert result["ok"] is True
    assert result["destination"] == str(out.resolve())
    assert result["files"] == 2 and result["bytes"] == 5
    assert len(result["sqlite"]) == 1 and result["sqlite"][0]["method"] == "backup"
    assert len(progress) == 2 and progress[-1]["index"] == 2
    manifest = json.loads((out / clone.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["source_unchanged"] is True
    assert manifest["source_git"]["branch"] == "main"
    assert manifest["safety"].startswith("read-only")


def test_create_full_clone_rejects_bad_git_and_staging(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    inv = _inv()
    monkeypatch.setattr(clone, "inventory", lambda root, **kwargs: inv)
    guard = {"head": "a", "branch": "main", "status": [], "active_mutators": []}
    with pytest.raises(PortableCloneError, match="failed fsck"):
        clone.create_full_clone(
            source,
            tmp_path / "out",
            writer_probe=lambda root: [], session_probe=lambda root: [],
            worktree_guard=lambda root: dict(guard), git_verifier=lambda root: {"ok": False},
        )

    monkeypatch.setattr(clone, "_validate_destination", lambda *a, **k: None)
    staging = (tmp_path / "out").with_name(f".out.partial-{clone.os.getpid()}")
    staging.mkdir()
    with pytest.raises(PortableCloneError, match="staging already exists"):
        clone.create_full_clone(
            source,
            tmp_path / "out",
            writer_probe=lambda root: [], session_probe=lambda root: [],
            worktree_guard=lambda root: dict(guard),
            git_verifier=lambda root: {"ok": True, "head": "a", "branch": "main", "remotes": []},
        )


def test_print_progress_and_main_paths(tmp_path, monkeypatch, capsys) -> None:
    clone._print_progress({"total": 2, "index": 1, "relative_path": "a", "copied_bytes": 1, "planned_bytes": 2})
    assert "1/2 a" in capsys.readouterr().out
    clone._print_progress({"total": 300, "index": 2, "relative_path": "b", "copied_bytes": 1, "planned_bytes": 2})
    assert capsys.readouterr().out == ""
    clone._print_progress({"total": 300, "index": 250, "relative_path": "c", "copied_bytes": 1, "planned_bytes": 2})
    assert "250/300 c" in capsys.readouterr().out

    monkeypatch.setattr(clone, "verify_clone", lambda path, full_hash: {"ok": True, "full_hash": full_hash})
    assert clone.main(["--verify", str(tmp_path), "--fast-verify"]) == 0
    assert '"full_hash": false' in capsys.readouterr().out.lower()
    monkeypatch.setattr(clone, "verify_clone", lambda path, full_hash: {"ok": False})
    assert clone.main(["--verify", str(tmp_path)]) == 4

    inv = _inv(PlannedFile("a", 10, "file"))
    monkeypatch.setattr(clone, "inventory", lambda root: inv)
    monkeypatch.setattr(clone, "automatic_destination", lambda bytes: tmp_path / "auto")
    assert clone.main(["--root", str(tmp_path), "--dry-run"]) == 0
    assert '"dry_run": true' in capsys.readouterr().out.lower()

    monkeypatch.setattr(clone, "create_full_clone", lambda *a, **k: {"ok": True, "destination": str(tmp_path / "out")})
    assert clone.main(["--root", str(tmp_path), "--destination", str(tmp_path / "dest")]) == 0
    assert "PORTABLE_FULL_CLONE_OK" in capsys.readouterr().out

    monkeypatch.setattr(clone, "inventory", lambda root: (_ for _ in ()).throw(PortableCloneError("refused")))
    assert clone.main(["--root", str(tmp_path)]) == 5
    assert "PORTABLE_FULL_CLONE_REFUSED" in capsys.readouterr().err

    monkeypatch.setattr(clone, "inventory", lambda root: (_ for _ in ()).throw(RuntimeError("boom")))
    assert clone.main(["--root", str(tmp_path)]) == 1
    assert "PORTABLE_FULL_CLONE_ERROR" in capsys.readouterr().err
