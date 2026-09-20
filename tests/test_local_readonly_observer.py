from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from local_readonly_observer_core import (
    compare_tracked_paths,
    inventory_tree,
    protected_source_signature,
    redact_text,
    validate_paths,
)
from local_readonly_observer_git import write_changed_text_snapshot
from local_readonly_observer_static import static_scan


def test_output_must_be_outside_observed_tree(tmp_path: Path) -> None:
    target = tmp_path / "local"
    github = tmp_path / "github"
    target.mkdir()
    github.mkdir()

    with pytest.raises(ValueError):
        validate_paths(target, github, target / "observer-output")

    external = tmp_path / "evidence"
    validate_paths(target, github, external)


def test_inventory_is_metadata_only_and_prunes_git(tmp_path: Path) -> None:
    target = tmp_path / "local"
    (target / "src").mkdir(parents=True)
    (target / "runtime" / "data").mkdir(parents=True)
    (target / ".git" / "objects").mkdir(parents=True)

    (target / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (target / "runtime" / "data" / "ticks.jsonl").write_text(
        '{"x":1}\n',
        encoding="utf-8",
    )
    (target / ".git" / "objects" / "private").write_text(
        "internal",
        encoding="utf-8",
    )

    rows, summary = inventory_tree(target)
    paths = {row["path"] for row in rows}

    assert "src/a.py" in paths
    assert "runtime/data/ticks.jsonl" in paths
    assert ".git/objects/private" not in paths
    assert summary["files"] == 2

    categories = {row["path"]: row["category"] for row in rows}
    assert categories["src/a.py"] == "source"
    assert categories["runtime/data/ticks.jsonl"] == "dataset"


def test_compare_tracked_detects_local_modification_and_deletion(tmp_path: Path) -> None:
    local = tmp_path / "local"
    github = tmp_path / "github"
    local.mkdir()
    github.mkdir()

    (local / "same.py").write_text("same\n", encoding="utf-8")
    (github / "same.py").write_text("same\n", encoding="utf-8")

    (local / "changed.py").write_text("local\n", encoding="utf-8")
    (github / "changed.py").write_text("github\n", encoding="utf-8")

    (github / "deleted.py").write_text("exists on github\n", encoding="utf-8")

    rows = compare_tracked_paths(
        local,
        github,
        ["same.py", "changed.py", "deleted.py"],
    )
    by_path = {row["path"]: row for row in rows}

    assert by_path["same.py"]["status"] == "same"
    assert by_path["changed.py"]["status"] == "modified_local"
    assert by_path["deleted.py"]["status"] == "deleted_local"


def test_static_scan_finds_markers_pass_and_hardcoded_user_path(tmp_path: Path) -> None:
    target = tmp_path / "local"
    source = target / "src"
    source.mkdir(parents=True)

    (source / "sample.py").write_text(
        "# TODO replace placeholder\n"
        "LOCAL = r'C:\\Users\\someone\\Desktop\\project'\n"
        "def unfinished():\n"
        "    pass\n",
        encoding="utf-8",
    )

    report = static_scan(target)
    kinds = {row["kind"] for row in report["findings"]}

    assert "marker" in kinds
    assert "hardcoded_user_path" in kinds
    assert "python_pass" in kinds


def test_changed_text_snapshot_redacts_obvious_credentials(tmp_path: Path) -> None:
    local = tmp_path / "local"
    github = tmp_path / "github"
    output = tmp_path / "evidence"
    local.mkdir()
    github.mkdir()
    output.mkdir()

    (local / "config.py").write_text(
        'api_key="super-secret-value"\nvalue = 2\n',
        encoding="utf-8",
    )
    (github / "config.py").write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    comparison = [{
        "path": "config.py",
        "status": "modified_local",
    }]
    result = write_changed_text_snapshot(
        local,
        github,
        output,
        comparison,
        [],
    )

    copied = (output / "changed_text" / "config.py").read_text(encoding="utf-8")
    assert "super-secret-value" not in copied
    assert "<REDACTED>" in copied
    assert result["files_included"] == 1


def test_protected_signature_changes_only_when_source_changes(tmp_path: Path) -> None:
    target = tmp_path / "local"
    (target / "src").mkdir(parents=True)
    (target / "runtime" / "data").mkdir(parents=True)

    source = target / "src" / "a.py"
    runtime = target / "runtime" / "data" / "ticks.jsonl"
    source.write_text("x = 1\n", encoding="utf-8")
    runtime.write_text('{"x":1}\n', encoding="utf-8")

    before = protected_source_signature(target)
    runtime.write_text('{"x":2}\n', encoding="utf-8")
    after_runtime = protected_source_signature(target)
    assert before == after_runtime

    source.write_text("x = 2\n", encoding="utf-8")
    after_source = protected_source_signature(target)
    assert before != after_source


def test_redact_text_keeps_non_secret_code() -> None:
    text, count = redact_text("value = 123\n")
    assert text == "value = 123\n"
    assert count == 0
