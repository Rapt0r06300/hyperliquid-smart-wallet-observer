from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from hl_observer.ops import portable_clone as PC


def _source(root: Path) -> Path:
    source = root / "source"
    required = {
        "LANCER_HYPERSMART.cmd": "@echo off\n",
        "ANALYSER_BACKTESTS_REPLAYS.cmd": "@echo off\n",
        "POUSSER-GITHUB-FORCE.cmd": "@echo off\n",
        "CREER_ARCHIVE_PORTABLE.cmd": "@echo off\n",
        "tools/portable_env.cmd": "@echo off\n",
        "tools/push_github_safe.ps1": "exit 0\n",
        "src/hl_observer/__init__.py": "",
        "src/hl_observer/ops/portable_smoke.py": "",
        "logs/live.log": "journal durable\n",
        "data/history.jsonl": '{"event":"OPEN"}\n',
        "runtime/data/report.json": '{"pnl":1}\n',
        ".git/config": "[core]\nrepositoryformatversion = 0\n",
    }
    for relative, content in required.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    python = source / "tools" / "python" / "python.exe"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"MZ-portable")
    git = source / "tools" / "git" / "cmd" / "git.exe"
    git.parent.mkdir(parents=True)
    git.write_bytes(b"MZ-git-portable")

    database = source / "runtime" / "data" / "ledger.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE ledger(id INTEGER PRIMARY KEY, pnl REAL)")
        connection.execute("INSERT INTO ledger(pnl) VALUES (1.25)")
        connection.commit()
    (source / "runtime" / "data" / "ledger.sqlite3-wal").write_bytes(b"not-copied")
    (source / "runtime" / "data" / "launcher_pids.json").write_text("{}", encoding="utf-8")
    sessions = source / "runtime" / "data" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "COURANTE.json").write_text('{"run_id":"old"}', encoding="utf-8")
    cache = source / "src" / "hl_observer" / "__pycache__"
    cache.mkdir()
    (cache / "module.pyc").write_bytes(b"cache")
    return source


def _no_writers(_root: str | Path) -> list[str]:
    return []


def _no_sessions(_root: str | Path) -> list[str]:
    return []


def _clean_worktree(_root: str | Path) -> dict[str, object]:
    return {
        "head": "1" * 40,
        "branch": "main",
        "status": [],
        "active_mutators": [],
    }


def _valid_git(_root: str | Path) -> dict[str, object]:
    return {
        "ok": True,
        "head": "1" * 40,
        "branch": "main",
        "remotes": ["origin https://example.invalid/repo.git (fetch)"],
        "fsck": "",
        "failures": {},
    }


def test_complete_clone_preserves_history_git_logs_and_coherent_sqlite(tmp_path: Path):
    source = _source(tmp_path)
    destination = tmp_path / "portable"

    result = PC.create_full_clone(
        source,
        destination,
        writer_probe=_no_writers,
        session_probe=_no_sessions,
        worktree_guard=_clean_worktree,
        git_verifier=_valid_git,
    )

    assert result["ok"] is True
    assert (destination / "logs" / "live.log").read_text(encoding="utf-8") == "journal durable\n"
    assert (destination / "data" / "history.jsonl").is_file()
    assert (destination / ".git" / "config").is_file()
    assert (destination / "tools" / "python" / "python.exe").read_bytes() == b"MZ-portable"
    assert (destination / "tools" / "git" / "cmd" / "git.exe").read_bytes() == b"MZ-git-portable"
    with sqlite3.connect(destination / "runtime" / "data" / "ledger.sqlite3") as connection:
        assert connection.execute("SELECT pnl FROM ledger").fetchone() == (1.25,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert not (destination / "runtime" / "data" / "ledger.sqlite3-wal").exists()
    assert not (destination / "runtime" / "data" / "launcher_pids.json").exists()
    assert not (destination / "runtime" / "data" / "sessions" / "COURANTE.json").exists()
    assert not (destination / "src" / "hl_observer" / "__pycache__").exists()

    manifest_text = (destination / PC.MANIFEST_NAME).read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert str(source) not in manifest_text
    assert manifest["durable_runtime_included"] is True
    assert manifest["git_history_included"] is True
    assert manifest["files"]["runtime/data/ledger.sqlite3"]["kind"] == "sqlite"
    assert manifest["durable_artifacts"]["ledgers"]["count"] >= 1
    assert manifest["durable_artifacts"]["histories"]["count"] >= 1
    verification = PC.verify_clone(destination, full_hash=True, git_verifier=_valid_git)
    assert verification["ok"] is True
    assert verification["git"]["branch"] == "main"
    assert verification["longest_path_ok"] is True
    assert verification["git_identity_matches_source"] is True
    assert verification["durable_artifacts_match_manifest"] is True


def test_clone_refuses_destination_inside_source(tmp_path: Path):
    source = _source(tmp_path)
    with pytest.raises(PC.PortableCloneError, match="outside"):
        PC.create_full_clone(
            source,
            source / "copy",
            writer_probe=_no_writers,
            session_probe=_no_sessions,
            worktree_guard=_clean_worktree,
            git_verifier=_valid_git,
        )


def test_clone_refuses_live_writer_before_copy(tmp_path: Path):
    source = _source(tmp_path)
    destination = tmp_path / "portable"
    with pytest.raises(PC.PortableCloneError, match="still active"):
        PC.create_full_clone(
            source,
            destination,
            writer_probe=lambda _root: ["PID_VIVANT:42"],
            session_probe=_no_sessions,
            worktree_guard=_clean_worktree,
            git_verifier=_valid_git,
        )
    assert not destination.exists()


def test_inventory_refuses_secret_but_accepts_env_example(tmp_path: Path):
    source = _source(tmp_path)
    (source / ".env.example").write_text("PUBLIC_SETTING=example\n", encoding="utf-8")
    assert any(item.relative_path == ".env.example" for item in PC.inventory(source).files)
    (source / ".env").write_text("SECRET=value\n", encoding="utf-8")
    with pytest.raises(PC.PortableCloneError, match="secret"):
        PC.inventory(source)


def test_cli_dry_run_does_not_create_destination(tmp_path: Path, capsys):
    source = _source(tmp_path)
    destination = tmp_path / "portable"
    code = PC.main(["--root", str(source), "--destination", str(destination), "--dry-run"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["dry_run"] is True
    assert payload["sqlite"] == 1
    assert not destination.exists()


def test_root_cmd_defaults_to_full_clone_and_keeps_small_zip_mode():
    root = Path(__file__).resolve().parents[1]
    text = (root / "CREER_ARCHIVE_PORTABLE.cmd").read_text(encoding="utf-8")
    assert "hl_observer.ops.portable_clone" in text
    assert "--application-seule" in text
    assert "hl_observer.ops.archive_portable" in text


def test_staging_failure_never_publishes_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _source(tmp_path)
    destination = tmp_path / "portable"
    monkeypatch.setattr(
        PC,
        "verify_clone",
        lambda *_args, **_kwargs: {"ok": False, "reason": "injected-staging-failure"},
    )
    with pytest.raises(PC.PortableCloneError, match="staging verification failed"):
        PC.create_full_clone(
            source,
            destination,
            writer_probe=_no_writers,
            session_probe=_no_sessions,
            worktree_guard=_clean_worktree,
            git_verifier=_valid_git,
        )
    assert not destination.exists()
    partials = list(tmp_path.glob(".portable.partial-*"))
    assert len(partials) == 1
    assert (partials[0] / "PORTABLE_CLONE_FAILED.txt").is_file()


def test_clone_refuses_source_change_before_publication(tmp_path: Path):
    source = _source(tmp_path)
    destination = tmp_path / "portable"
    calls = 0

    def changing_guard(_root: str | Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        payload = _clean_worktree(_root)
        payload["head"] = str(calls) * 40
        return payload

    with pytest.raises(PC.PortableCloneError, match="identity changed"):
        PC.create_full_clone(
            source,
            destination,
            writer_probe=_no_writers,
            session_probe=_no_sessions,
            worktree_guard=changing_guard,
            git_verifier=_valid_git,
        )
    assert not destination.exists()


def test_inventory_refuses_unapproved_symlink_or_reparse(tmp_path: Path):
    source = _source(tmp_path)
    link = source / "linked-runtime"
    try:
        link.symlink_to(source / "runtime", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not available on this Windows account")
    with pytest.raises(PC.PortableCloneError, match="reparse point refused"):
        PC.inventory(source)
