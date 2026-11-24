from __future__ import annotations

from pathlib import Path

from launcher_lifecycle import ProcessInfo, descendant_pids, is_excluded_commandline, parse_snapshot, should_track

ROOT = Path(__file__).resolve().parents[1]


def _p(pid: int, parent: int, commandline: str, name: str = "python.exe") -> ProcessInfo:
    return ProcessInfo(pid, parent, name, commandline)


def test_parse_snapshot_accepts_singleton_and_list() -> None:
    one = parse_snapshot('{"ProcessId": 7, "ParentProcessId": 3, "Name": "cmd.exe", "CommandLine": "x"}')
    many = parse_snapshot('[{"ProcessId": 8, "ParentProcessId": 7, "Name": "python.exe", "CommandLine": "y", "CreatedAt": 1795384068}]')
    assert one[7].parent_pid == 3
    assert many[8].name == "python.exe"
    assert many[8].created_at == 1795384068.0


def test_descendant_pids_walks_all_generations() -> None:
    snapshot = {1: _p(1, 0, "cmd"), 2: _p(2, 1, "cmd"), 3: _p(3, 2, "python"), 4: _p(4, 3, "worker")}
    assert descendant_pids(snapshot, 1) == {2, 3, 4}


def test_should_track_requires_scope_and_excludes_adjacent_claude() -> None:
    root = Path(r"C:\Users\flo\Desktop\Projet invest")
    launcher = root / "LANCER_LAB_QUANT_COPY_VAULT.cmd"
    owned = _p(2, 1, f'python "{root / "tools" / "lab.py"}"')
    unrelated = _p(3, 1, r'python "C:\Users\flo\AppData\Local\ClaudeCode-Official-Max\run.py"')
    related = _p(4, 9, "python --name coffre-certificateur")
    assert should_track(owned, root=root, launcher=launcher)
    assert not should_track(unrelated, root=root, launcher=launcher)
    assert should_track(related, root=root, launcher=launcher, related_patterns=("coffre-certificateur",))


def test_exclusion_is_case_insensitive() -> None:
    assert is_excluded_commandline("C:\\SALAD\\worker.exe")
    assert is_excluded_commandline("C:/Users/flo/.codex/bin.exe")


def test_every_root_cmd_registers_the_shared_guard() -> None:
    launchers = sorted(ROOT.glob("*.cmd"))
    assert len(launchers) == 14
    missing = [p.name for p in launchers if "launcher_lifecycle.cmd" not in p.read_text(encoding="utf-8")]
    assert missing == []
