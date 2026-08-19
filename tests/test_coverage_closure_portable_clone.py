from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

import hl_observer.ops.portable_clone as clone
from hl_observer.ops.portable_clone_inventory import CloneInventory, PlannedFile, PortableCloneError


def _inventory(*files: PlannedFile) -> CloneInventory:
    return CloneInventory(
        files=tuple(files),
        excluded=(),
        total_bytes=sum(item.size for item in files),
        sqlite_count=sum(item.kind == "sqlite" for item in files),
        longest_relative_path=max((len(item.relative_path) for item in files), default=0),
        longest_relative_member=max(
            (files or (PlannedFile("", 0, "file"),)),
            key=lambda item: len(item.relative_path),
        ).relative_path,
    )


def test_copy_hash_and_validate_destination(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"abcdef")
    destination = tmp_path / "nested" / "copy.bin"
    digest, size = clone._copy_and_hash(source, destination, buffer_size=2)
    assert digest == hashlib.sha256(b"abcdef").hexdigest()
    assert size == 6 and destination.read_bytes() == b"abcdef"
    assert clone._hash_file(destination, buffer_size=3) == (digest, 6)

    root = tmp_path / "project"
    root.mkdir()
    inv = _inventory(PlannedFile("x", 10, "file"))
    with pytest.raises(PortableCloneError, match="outside and separate"):
        clone._validate_destination(root, root / "child", inv)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(PortableCloneError, match="already exists"):
        clone._validate_destination(root, existing, inv)
    monkeypatch.setattr(clone.shutil, "disk_usage", lambda parent: SimpleNamespace(free=1))
    with pytest.raises(PortableCloneError, match="not enough free space"):
        clone._validate_destination(root, tmp_path / "dest", inv)


def test_verify_git_repository_and_worktree_guard(tmp_path, monkeypatch) -> None:
    embedded = tmp_path / "tools" / "git" / "cmd" / "git.exe"
    embedded.parent.mkdir(parents=True)
    embedded.write_text("fake", encoding="utf-8")
    outputs = {
        ("fsck", "--full"): SimpleNamespace(returncode=0, stdout="ok\n", stderr=""),
        ("rev-parse", "HEAD"): SimpleNamespace(returncode=0, stdout="a" * 40 + "\n", stderr=""),
        ("branch", "--show-current"): SimpleNamespace(returncode=0, stdout="main\n", stderr=""),
        ("remote", "-v"): SimpleNamespace(returncode=0, stdout="origin url (fetch)\n", stderr=""),
    }
    monkeypatch.setattr(
        clone,
        "_git_command",
        lambda root, *args, timeout=0: outputs[tuple(args)],
    )
    result = clone.verify_git_repository(tmp_path)
    assert result["ok"] is True and result["branch"] == "main"

    (tmp_path / ".git").mkdir(exist_ok=True)
    monkeypatch.setattr(clone, "_active_project_mutators", lambda root: [])

    def clean_git(root, *args, timeout=120):
        if args[0] == "status":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[0] == "rev-parse":
            return SimpleNamespace(returncode=0, stdout="a" * 40 + "\n", stderr="")
        if args[0] == "branch":
            return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(clone, "_git_command", clean_git)
    guard = clone.source_worktree_guard(tmp_path)
    assert guard["head"] == "a" * 40 and guard["branch"] == "main"


def _required_files(root) -> list[str]:
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
    for relative in required:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    return required


def test_verify_clone_missing_invalid_success_and_divergence(tmp_path, monkeypatch) -> None:
    root = tmp_path / "clone"
    root.mkdir()
    assert clone.verify_clone(root)["reason"] == "manifest_missing"
    manifest_path = root / clone.MANIFEST_NAME
    manifest_path.write_text("bad", encoding="utf-8")
    assert clone.verify_clone(root)["reason"].startswith("manifest_invalid:")

    required = _required_files(root)
    empty_sha = hashlib.sha256(b"").hexdigest()
    files = {
        relative: {"size": 0, "sha256": empty_sha, "kind": "file"}
        for relative in required
    }
    source_git = {"head": "a" * 40, "branch": "main", "remotes": ["origin"]}
    manifest = {
        "schema_version": 2,
        "files": files,
        "durable_artifacts": clone._durable_artifact_summary(files),
        "source_git": source_git,
        "source_machine_fingerprint": "pc-a",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(clone, "machine_fingerprint", lambda: "pc-b")
    git = {"ok": True, **source_git}
    row = clone.verify_clone(root, git_verifier=lambda path: dict(git))
    assert row["ok"] is True and row["physical_machine_distinct"] is True

    (root / required[0]).write_bytes(b"x")
    row = clone.verify_clone(root, git_verifier=lambda path: dict(git))
    assert row["ok"] is False and required[0] in row["divergent"]


def test_create_full_clone_guards_and_success(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("abc", encoding="utf-8")
    inv = _inventory(PlannedFile("a.txt", 3, "file"))
    with pytest.raises(PortableCloneError, match="writers are still active"):
        clone.create_full_clone(
            source,
            tmp_path / "out",
            writer_probe=lambda root: ["writer"],
            session_probe=lambda root: [],
        )
    with pytest.raises(PortableCloneError, match="active sessions"):
        clone.create_full_clone(
            source,
            tmp_path / "out",
            writer_probe=lambda root: [],
            session_probe=lambda root: ["session"],
        )

    monkeypatch.setattr(clone, "inventory", lambda root, **kwargs: inv)
    monkeypatch.setattr(clone, "_validate_destination", lambda *args, **kwargs: None)
    monkeypatch.setattr(clone, "machine_fingerprint", lambda: "machine")
    monkeypatch.setattr(
        clone,
        "verify_clone",
        lambda root, **kwargs: {"ok": True, "root": str(root)},
    )
    guard = {"head": "a" * 40, "branch": "main", "status": [], "active_mutators": []}
    git = {"ok": True, "head": "a" * 40, "branch": "main", "remotes": ["origin"]}
    out = tmp_path / "out"
    result = clone.create_full_clone(
        source,
        out,
        writer_probe=lambda root: [],
        session_probe=lambda root: [],
        worktree_guard=lambda root: dict(guard),
        git_verifier=lambda root: dict(git),
    )
    assert result["ok"] is True
    assert result["files"] == 1 and result["bytes"] == 3
    manifest = json.loads((out / clone.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["source_unchanged"] is True
    assert manifest["safety"].startswith("read-only")


def test_print_progress_and_main_paths(tmp_path, monkeypatch, capsys) -> None:
    clone._print_progress({
        "total": 2,
        "index": 1,
        "relative_path": "a",
        "copied_bytes": 1,
        "planned_bytes": 2,
    })
    assert "1/2 a" in capsys.readouterr().out
    monkeypatch.setattr(clone, "verify_clone", lambda path, full_hash: {"ok": True})
    assert clone.main(["--verify", str(tmp_path)]) == 0
    monkeypatch.setattr(
        clone,
        "inventory",
        lambda root: (_ for _ in ()).throw(PortableCloneError("refused")),
    )
    assert clone.main(["--root", str(tmp_path)]) == 5
