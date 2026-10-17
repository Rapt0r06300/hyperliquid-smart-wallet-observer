"""Fail-closed, deterministic bounds for accelerated historical reconciliation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.select_reconciliation_batch import apply_plan, select_prefix


def write_manifest(root: Path, tag: str, count: int, *, repository: str | None = None) -> None:
    path = root / tag / "RUN_MANIFEST.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "alina.dataset_run_manifest.v2",
        "repository": repository or "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "manifests": [{"dataset_id": f"{tag}-{i}"} for i in range(count)],
    }), encoding="utf-8")


def test_bounded_prefix_is_deterministic_and_never_skips(tmp_path: Path) -> None:
    for tag in ("a", "b", "c"):
        write_manifest(tmp_path, tag, 4)
    assert select_prefix(["a", "b", "c"], tmp_path, max_shards=9,
                         max_manifest_bytes=100000) == (["a", "b"], 8)
    assert select_prefix(["a", "b", "c"], tmp_path, max_shards=9,
                         max_manifest_bytes=100000) == (["a", "b"], 8)


def test_oversized_first_release_is_refused_without_dropping_evidence(tmp_path: Path) -> None:
    write_manifest(tmp_path, "a", 6)
    with pytest.raises(ValueError, match="single Release"):
        select_prefix(["a"], tmp_path, max_shards=5, max_manifest_bytes=100000)
    assert (tmp_path / "a" / "RUN_MANIFEST.json").exists()


def test_foreign_or_missing_manifest_is_fail_closed(tmp_path: Path) -> None:
    write_manifest(tmp_path, "a", 1, repository="someone/else")
    with pytest.raises(ValueError, match="invalid immutable"):
        select_prefix(["a"], tmp_path, max_shards=5, max_manifest_bytes=100000)
    with pytest.raises(ValueError, match="missing"):
        select_prefix(["missing"], tmp_path, max_shards=5, max_manifest_bytes=100000)


def test_apply_plan_prunes_only_deferred_downloads_and_tracks_backlog(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    for tag in ("a", "b", "c"):
        write_manifest(root, tag, 4)
    tags = tmp_path / "tags.txt"
    total = tmp_path / "tags.count"
    env = tmp_path / "github-env"
    tags.write_text("a\nb\nc\n", encoding="utf-8")
    total.write_text("115\n", encoding="utf-8")
    assert apply_plan(root, tags, total, env, max_shards=9,
                      max_manifest_bytes=100000) == (2, 113)
    assert tags.read_text(encoding="utf-8") == "a\nb\n"
    assert (root / "a" / "RUN_MANIFEST.json").exists()
    assert (root / "b" / "RUN_MANIFEST.json").exists()
    assert not (root / "c").exists()
    assert "REMAINING_NEW_TAGS=113" in env.read_text(encoding="utf-8")


def test_invalid_tag_cannot_escape_download_root(tmp_path: Path) -> None:
    write_manifest(tmp_path, "okay", 1)
    with pytest.raises(ValueError, match="invalid or repeated"):
        select_prefix(["okay", "../outside"], tmp_path,
                      max_shards=100, max_manifest_bytes=100000)


def test_byte_budget_bounds_prefix_even_when_shard_budget_has_room(tmp_path: Path) -> None:
    write_manifest(tmp_path, "a", 2)
    write_manifest(tmp_path, "b", 2)
    bytes_first = (tmp_path / "a" / "RUN_MANIFEST.json").stat().st_size
    assert select_prefix(
        ["a", "b"], tmp_path, max_shards=100,
        max_manifest_bytes=bytes_first,
    ) == (["a"], 2)
    assert (tmp_path / "b" / "RUN_MANIFEST.json").is_file()



def test_historical_workflow_never_cancels_active_reconciliation() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github" / "workflows" / "reconcile-v2-catalog.yml"
    ).read_text(encoding="utf-8")
    assert "group: dataset-v2-catalog-reconcile" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "batch_size = 1" in workflow
    assert "--max-shards 60000" in workflow
    assert "--max-manifest-bytes 67108864" in workflow
    assert "Continue certified historical waves on the same hosted runner" in workflow
    assert "cancel-in-progress: ${{ github.event_name == 'push' }}" not in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "self-hosted" not in workflow.split("runs-on: ubuntu-latest")[1].split("steps:")[0]


def test_noop_compaction_skips_redundant_global_metrics() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github" / "workflows" / "reconcile-v2-catalog.yml"
    ).read_text(encoding="utf-8")
    diagnostic = workflow.split(
        "- name: Measure canonical index field weights before reconciliation", 1
    )[1].split("- name: Compact existing canonical index before growing it", 1)[0]
    assert "if: github.event_name == 'workflow_dispatch'" in diagnostic
    segment = workflow.split(
        "- name: Compact existing canonical index before growing it", 1
    )[1].split("- name: Download new Dataset principal run manifests", 1)[0]
    assert segment.index("git add catalog") < segment.index("if git diff --cached --quiet")
    assert segment.index("if git diff --cached --quiet") < segment.index("python tools/build_catalog_metrics.py")
    assert segment.index("python tools/check_dataset_quality.py") < segment.index('git commit -m "data: losslessly compact canonical run locators"')
    assert "git reset --hard origin/main" in segment


def test_oversized_starter_accepts_only_first_with_explicit_hard_cap(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    for tag in ("big", "next"):
        write_manifest(root, tag, 12)
    tags = tmp_path / "tags.txt"
    total = tmp_path / "count"
    env = tmp_path / "env"
    tags.write_text("big\nnext\n", encoding="utf-8")
    total.write_text("200", encoding="utf-8")
    selected, remaining = apply_plan(
        root, tags, total, env, max_shards=8, max_manifest_bytes=100000,
        max_first_shards=15,
    )
    assert (selected, remaining) == (1, 199)
    assert (root / "big" / "RUN_MANIFEST.json").is_file()
    assert not (root / "next").exists()
    assert "REMAINING_NEW_TAGS=199" in env.read_text(encoding="utf-8")


def test_oversized_starter_cannot_exceed_100k_or_skip_a_giant(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    write_manifest(root, "giant", 25)
    tags = tmp_path / "tags.txt"
    total = tmp_path / "count"
    env = tmp_path / "env"
    tags.write_text("giant\n", encoding="utf-8")
    total.write_text("1", encoding="utf-8")
    with pytest.raises(ValueError, match="single Release"):
        apply_plan(root, tags, total, env, max_shards=8,
                   max_manifest_bytes=100000, max_first_shards=20)
    assert (root / "giant" / "RUN_MANIFEST.json").exists()


def test_deferred_tag_traversal_is_rejected_before_temporary_cleanup(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    write_manifest(root, "normal", 4)
    outside = tmp_path / "unrelated"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("must remain", encoding="utf-8")
    tags = tmp_path / "tags.txt"
    total = tmp_path / "count"
    env = tmp_path / "env"
    tags.write_text("normal\n../unrelated\n", encoding="utf-8")
    total.write_text("2", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid or repeated deferred"):
        apply_plan(root, tags, total, env, max_shards=4,
                   max_manifest_bytes=100000)
    assert marker.read_text(encoding="utf-8") == "must remain"
