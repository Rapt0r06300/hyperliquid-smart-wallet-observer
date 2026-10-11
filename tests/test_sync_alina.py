from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("alina_sync_test", ROOT / "tools" / "sync_alina.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_canonical_remote_accepts_only_original_repository():
    module = _module()
    assert module._canonical_origin(
        "https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer.git"
    )
    assert module._canonical_origin(
        "git@github.com:Rapt0r06300/hyperliquid-smart-wallet-observer.git"
    )
    assert module._canonical_origin(
        "ssh://git@github.com/Rapt0r06300/hyperliquid-smart-wallet-observer"
    )
    assert not module._canonical_origin(
        "https://github.com/unrelated/hyperliquid-smart-wallet-observer.git"
    )
    assert not module._canonical_origin("https://evil.example/repository")


def test_sync_refuses_dirty_checkout_before_fetch(monkeypatch):
    module = _module()
    calls = []

    def fake_git(*args):
        calls.append(args)
        if args[:2] == ("remote", "get-url"):
            return "https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer.git"
        if args[0] == "symbolic-ref":
            return "main"
        if args[0] == "status":
            return " M tools/restore_alina.py"
        raise AssertionError("unexpected Git operation on dirty checkout")

    monkeypatch.setattr(module, "_git", fake_git)
    try:
        module.sync_main()
    except module.SyncError as exc:
        assert "tracked local changes" in str(exc)
    else:
        raise AssertionError("dirty checkout must not update")
    assert all(args[0] not in ("fetch", "merge") for args in calls)


def test_sync_uses_fast_forward_only(monkeypatch):
    module = _module()
    operations = []

    def fake_git(*args):
        operations.append(args)
        if args[0] == "remote":
            return "https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer.git"
        if args[0] == "symbolic-ref":
            return "main"
        if args[0] == "status":
            return ""
        if args[0] == "rev-parse":
            return "a" * 40 if operations.count(("rev-parse", "HEAD")) == 1 else "b" * 40
        return ""

    monkeypatch.setattr(module, "_git", fake_git)
    assert module.sync_main() == ("a" * 40, "b" * 40)
    assert ("fetch", "--no-tags", "origin", "main") in operations
    assert ("merge", "--ff-only", "FETCH_HEAD") in operations
    assert not any(op[0] in ("reset", "clean", "push", "rebase") for op in operations)


def test_sync_runs_restore_with_safety_defaults_and_records_checkpoint(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "sync_main", lambda: ("a" * 40, "b" * 40))
    called = []

    def fake_run(command, **kwargs):
        called.append((command, kwargs))
        if command[:3] == ["gh", "auth", "token"]:
            return SimpleNamespace(returncode=1, stdout="")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert module.main([]) == 0
    command = called[-1][0]
    assert command[1:3] == ["tools/restore_alina.py", "--everything"]
    assert "--recover-verifiable" in command
    assert "--materialize-available-local-snapshot" in command
    assert "--clone-root" not in command
    assert "--repository" in command
    report = json.loads((tmp_path / "runtime/recovery/full/SYNC_REPORT.json").read_text())
    assert report["status"] == "RESTORE_EXIT_ZERO"
    assert report["head_after"] == "b" * 40


def test_sync_preserves_incomplete_restore_exit_code(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "sync_main", lambda: ("a" * 40, "a" * 40))
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=3)
    )
    assert module.main(["--preflight-only"]) == 3
    report = json.loads((tmp_path / "runtime/recovery/full/SYNC_REPORT.json").read_text())
    assert report["status"] == "RESTORE_INCOMPLETE"
    assert report["restore_exit_code"] == 3


def test_sync_refuses_invalid_options_without_git_or_network(monkeypatch):
    module = _module()
    monkeypatch.setattr(
        module, "sync_main",
        lambda: (_ for _ in ()).throw(AssertionError("must not reach Git"))
    )
    assert module.main(["--repository", "other/repo"]) == 2
    assert module.main(["--materialize-local-snapshot",
                        "--materialize-available-local-snapshot"]) == 2


def test_standard_restore_does_not_activate_lfs():
    from pathlib import Path
    restore = (ROOT / "tools" / "restore_alina.py").read_text(encoding="utf-8")
    launcher = (ROOT / "RESTORE_ALINA.cmd").read_text(encoding="utf-8")
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert 'parser.add_argument("--clone-root", default=None' in restore
    assert '--clone-root "."' not in launcher
    assert not any(line.strip().startswith("*.") and "filter=lfs" in line
                   for line in attributes.splitlines())
