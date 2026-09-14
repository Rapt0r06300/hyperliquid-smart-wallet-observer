from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.ops import full_folder_release as FFR


def test_inventory_is_exact_and_excludes_only_build_directory(tmp_path: Path):
    root = tmp_path / "repo"
    output = root / "runtime" / "portable-build" / "release"
    (root / "empty").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "data" / "large.bin").write_bytes(b"abc" * 100)
    output.mkdir(parents=True)
    (output / "must-not-self-include.bin").write_bytes(b"x")

    entries = FFR.inventory_source(root, exclude=output)
    by_path = {entry.path: entry for entry in entries}

    assert by_path["data/large.bin"].sha256 == FFR.sha256_file(root / "data" / "large.bin")
    assert by_path["empty"].kind == "directory"
    assert not any(entry.path.startswith("runtime/portable-build/release") for entry in entries)


def test_secret_filenames_fail_closed_but_templates_are_allowed(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env.example").write_text("PUBLIC=yes", encoding="utf-8")
    assert FFR.inventory_source(root)
    (root / ".env").write_text("SECRET=yes", encoding="utf-8")
    with pytest.raises(FFR.FullFolderReleaseError, match="secret filename"):
        FFR.inventory_source(root)


def test_plan_and_finalize_hash_every_release_asset(tmp_path: Path):
    root = tmp_path / "repo"
    output = root / "build"
    root.mkdir()
    (root / "hello.txt").write_text("bonjour", encoding="utf-8")
    planned = FFR.write_plan(root, output, "a" * 40)
    assert planned["file_count"] == 1
    (output / f"{FFR.ARCHIVE_BASENAME}.001").write_bytes(b"part-one")
    (output / f"{FFR.ARCHIVE_BASENAME}.002").write_bytes(b"part-two")

    manifest = FFR.finalize(root, output, "full-a", "a" * 40, "owner/repo")

    assert manifest["archive_first_part"].endswith(".001")
    assert [asset["size"] for asset in manifest["archive_assets"]] == [8, 8]
    on_disk = json.loads((output / FFR.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert on_disk == manifest


def test_finalize_refuses_a_source_modified_during_build(tmp_path: Path):
    root = tmp_path / "repo"
    output = root / "build"
    root.mkdir()
    source = root / "hello.txt"
    source.write_text("before", encoding="utf-8")
    FFR.write_plan(root, output, "b" * 40)
    (output / f"{FFR.ARCHIVE_BASENAME}.001").write_bytes(b"archive")
    source.write_text("after with another size", encoding="utf-8")
    with pytest.raises(FFR.FullFolderReleaseError, match="source changed"):
        FFR.finalize(root, output, "full-b", "b" * 40, "owner/repo")


def test_internal_directory_link_is_recorded_and_never_traversed(tmp_path: Path):
    root = tmp_path / "repo"
    target = root / "runtime" / "data"
    target.mkdir(parents=True)
    (target / "one.bin").write_bytes(b"1")
    link = root / "linked-data"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory links unavailable")
    entries = FFR.inventory_source(root)
    linked = next(entry for entry in entries if entry.path == "linked-data")
    assert linked.kind == "junction"
    assert linked.target == "runtime/data"
    assert not any(entry.path.startswith("linked-data/") for entry in entries)
