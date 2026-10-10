from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from download_release_manifests import download_release_manifests  # noqa: E402


def _tag(command: list[str]) -> str:
    return command[3]


def _destination(command: list[str]) -> Path:
    return Path(command[command.index("--dir") + 1])


def test_eventually_visible_manifest_is_downloaded_after_one_global_wait(tmp_path) -> None:
    views: dict[str, int] = {}
    sleeps: list[float] = []

    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        tag = _tag(command)
        if command[2] == "view":
            views[tag] = views.get(tag, 0) + 1
            assets = "" if views[tag] == 1 else "RUN_MANIFEST.json\n"
            return subprocess.CompletedProcess(command, 0, assets, "")
        destination = _destination(command)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "RUN_MANIFEST.json").write_text('{"schema":"v2"}\n')
        return subprocess.CompletedProcess(command, 0, "", "")

    result = download_release_manifests(
        repository="owner/dataset",
        tags=["data-v2-123-s0"],
        destination=tmp_path,
        attempts=3,
        poll_seconds=4.0,
        runner=runner,
        sleeper=sleeps.append,
    )

    assert result.downloaded == ("data-v2-123-s0",)
    assert result.missing == ()
    assert result.attempts == 2
    assert sleeps == [4.0]
    assert (tmp_path / "data-v2-123-s0" / "RUN_MANIFEST.json").stat().st_size > 0


def test_download_error_is_retried_even_after_asset_is_listed(tmp_path) -> None:
    downloads = 0

    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal downloads
        if command[2] == "view":
            return subprocess.CompletedProcess(command, 0, "RUN_MANIFEST.json\n", "")
        downloads += 1
        if downloads == 1:
            return subprocess.CompletedProcess(command, 1, "", "no assets to download")
        destination = _destination(command)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "RUN_MANIFEST.json").write_text("{}\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = download_release_manifests(
        repository="owner/dataset",
        tags=["copy-vault-v2-456-s0"],
        destination=tmp_path,
        attempts=2,
        poll_seconds=0,
        runner=runner,
        sleeper=lambda _: None,
    )

    assert downloads == 2
    assert result.downloaded == ("copy-vault-v2-456-s0",)
    assert result.missing == ()


def test_exhausted_or_empty_manifest_stays_missing(tmp_path) -> None:
    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[2] == "view":
            tag = _tag(command)
            assets = "RUN_MANIFEST.json\n" if tag.endswith("empty") else ""
            return subprocess.CompletedProcess(command, 0, assets, "")
        destination = _destination(command)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "RUN_MANIFEST.json").write_bytes(b"")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = download_release_manifests(
        repository="owner/dataset",
        tags=["data-v2-missing", "data-v2-empty"],
        destination=tmp_path,
        attempts=2,
        poll_seconds=0,
        runner=runner,
        sleeper=lambda _: None,
    )

    assert result.downloaded == ()
    assert result.missing == ("data-v2-empty", "data-v2-missing")
    assert not list(tmp_path.rglob("RUN_MANIFEST.json"))


def test_tags_are_deduplicated_without_changing_order(tmp_path) -> None:
    downloads: list[str] = []

    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        tag = _tag(command)
        if command[2] == "view":
            return subprocess.CompletedProcess(command, 0, "RUN_MANIFEST.json\n", "")
        downloads.append(tag)
        destination = _destination(command)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "RUN_MANIFEST.json").write_text("{}\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = download_release_manifests(
        repository="owner/dataset",
        tags=["data-v2-a", "data-v2-a", "data-v2-b"],
        destination=tmp_path,
        attempts=1,
        poll_seconds=0,
        runner=runner,
        sleeper=lambda _: None,
    )

    assert downloads == ["data-v2-a", "data-v2-b"]
    assert result.downloaded == ("data-v2-a", "data-v2-b")




def test_listing_retries_504_per_page_without_discarding_previous_pages():
    from download_release_manifests import list_release_manifest_tags
    calls = []
    sleeps = []
    def runner(command, **_):
        endpoint = command[-1]
        calls.append(endpoint)
        if endpoint.endswith("page=1"):
            body = [
                {"id": 10, "tag_name": "data-v2-1", "assets": [{"name": "RUN_MANIFEST.json"}]},
                {"id": 11, "tag_name": "data-v2-2", "assets": []},
            ]
            return subprocess.CompletedProcess(command, 0, __import__("json").dumps(body), "")
        if len([x for x in calls if x.endswith("page=2")]) == 1:
            return subprocess.CompletedProcess(command, 1, "", "HTTP 504 gateway timeout")
        return subprocess.CompletedProcess(
            command, 0, __import__("json").dumps([
                {"id": 12, "tag_name": "data-v2-3", "assets": [{"name": "RUN_MANIFEST.json"}]}
            ]), ""
        )
    got = list_release_manifest_tags(
        "owner/repo", page_size=2, runner=runner, sleeper=sleeps.append,
    )
    assert got == [("data-v2-1", True), ("data-v2-2", False), ("data-v2-3", True)]
    assert len([x for x in calls if x.endswith("page=1")]) == 1
    assert len([x for x in calls if x.endswith("page=2")]) == 2
    assert sleeps == [2.0]


def test_listing_reads_truncated_asset_pages():
    from download_release_manifests import list_release_manifest_tags
    import json
    calls = []
    def runner(command, **_):
        endpoint = command[-1]
        calls.append(endpoint)
        if "/assets?" in endpoint:
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"id": 99, "name": "RUN_MANIFEST.json"}]), ""
            )
        if endpoint.endswith("page=1"):
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"id": 10, "tag_name": "data-v2-late",
                                        "assets": [{"name": str(i)} for i in range(30)]}]), ""
            )
        raise AssertionError(endpoint)
    out = list_release_manifest_tags("owner/repo", page_size=50, runner=runner)
    assert out == [("data-v2-late", True)]
    assert any("/assets?" in url for url in calls)


def test_listing_refuses_partial_inventory_on_permanent_http_504():
    from download_release_manifests import list_release_manifest_tags
    import pytest
    calls = []
    def runner(command, **_):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "HTTP 504 timed out")
    with pytest.raises(RuntimeError, match="after 2 attempt"):
        list_release_manifest_tags(
            "owner/repo", runner=runner, sleeper=lambda _: None, attempts=2,
        )
    assert len(calls) == 2


def test_listing_rejects_duplicate_release_ids():
    from download_release_manifests import list_release_manifest_tags
    import json
    def runner(command, **_):
        return subprocess.CompletedProcess(
            command, 0, json.dumps([
                {"id": 10, "tag_name": "data-v2-1", "assets": []},
                {"id": 10, "tag_name": "data-v2-2", "assets": []},
            ]), ""
        )
    import pytest
    with pytest.raises(RuntimeError, match="duplicated Release id"):
        list_release_manifest_tags("owner/repo", runner=runner)



def test_release_listing_tolerates_stable_overlapping_pages_from_new_live_releases():
    import json
    from download_release_manifests import list_release_manifest_tags

    def runner(cmd, **_kwargs):
        page = int(cmd[-1].split("page=")[-1])
        items = {
            1: [
                {"id": 4, "tag_name": "data-v2-d", "assets": []},
                {"id": 3, "tag_name": "data-v2-c", "assets": [{"name": "RUN_MANIFEST.json"}]},
            ],
            2: [
                {"id": 3, "tag_name": "data-v2-c", "assets": [{"name": "RUN_MANIFEST.json"}]},
                {"id": 2, "tag_name": "data-v2-b", "assets": []},
            ],
            3: [
                {"id": 2, "tag_name": "data-v2-b", "assets": []},
                {"id": 1, "tag_name": "data-v2-a", "assets": [{"name": "RUN_MANIFEST.json"}]},
            ],
            4: [],
        }
        return subprocess.CompletedProcess(cmd, 0, json.dumps(items[page]), "")

    result = list_release_manifest_tags(
        "owner/repo", page_size=2, runner=runner, sleeper=lambda _: None,
    )
    assert result == [
        ("data-v2-d", False), ("data-v2-c", True),
        ("data-v2-b", False), ("data-v2-a", True),
    ]


def test_release_listing_rejects_conflicting_reused_tag_across_pages():
    import json
    import pytest
    from download_release_manifests import list_release_manifest_tags

    def runner(cmd, **_kwargs):
        page = int(cmd[-1].split("page=")[-1])
        return subprocess.CompletedProcess(cmd, 0, json.dumps({
            1: [
                {"id": 12, "tag_name": "data-v2-a", "assets": []},
                {"id": 11, "tag_name": "data-v2-b", "assets": []},
            ],
            2: [{"id": 10, "tag_name": "data-v2-a", "assets": []}],
        }[page]), "")

    with pytest.raises(RuntimeError, match="conflicting Release"):
        list_release_manifest_tags(
            "owner/repo", page_size=2, runner=runner, sleeper=lambda _: None,
        )

def test_scoped_release_inventory_skips_known_and_unrelated_asset_lookups(tmp_path):
    import json
    from download_release_manifests import _known_tags_from_index, list_release_manifest_tags
    index = tmp_path / "DATA_INDEX.json"
    index.write_text(json.dumps({"shards": [
        {"dataset_id": "physical-1", "release_tag": "data-v2-physical", "run_manifest_release_tag": "data-v2-canonical"},
        {"dataset_id": "physical-2", "release_tag": "archive-v2-part"},
    ]}), encoding="utf-8")
    known = _known_tags_from_index(index)
    calls = []
    def runner(command, **_kwargs):
        endpoint = command[-1]
        calls.append(endpoint)
        if "/assets?" in endpoint:
            assert "/releases/30/" in endpoint
            return subprocess.CompletedProcess(command, 0, json.dumps([{"name": "RUN_MANIFEST.json"}]), "")
        assert endpoint.endswith("page=1")
        return subprocess.CompletedProcess(command, 0, json.dumps([
            {"id": 10, "tag_name": "data-v2-canonical", "assets": [{"name": str(i)} for i in range(30)]},
            {"id": 20, "tag_name": "alina-recovery-unrelated", "assets": [{"name": str(i)} for i in range(30)]},
            {"id": 30, "tag_name": "data-v2-new", "assets": [{"name": str(i)} for i in range(30)]},
        ]), "")
    assert list_release_manifest_tags(
        "owner/repo", runner=runner, skip_tags=known, only_production=True,
    ) == [("data-v2-new", True)]
    assert len([e for e in calls if "/assets?" in e]) == 1


def test_embedded_manifest_saves_asset_query_when_list_is_full():
    import json
    from download_release_manifests import list_release_manifest_tags
    calls = []
    def runner(command, **_kwargs):
        calls.append(command[-1])
        assert "/assets?" not in command[-1]
        return subprocess.CompletedProcess(command, 0, json.dumps([
            {"id": 1, "tag_name": "data-v2-visible",
             "assets": [{"name": str(i)} for i in range(29)] + [{"name": "RUN_MANIFEST.json"}]},
        ]), "")
    assert list_release_manifest_tags("owner/repo", runner=runner) == [("data-v2-visible", True)]
    assert len(calls) == 1


def test_invalid_reconcile_index_aliases_fail_closed(tmp_path):
    import json
    import pytest
    from download_release_manifests import _known_tags_from_index
    index = tmp_path / "DATA_INDEX.json"
    index.write_text(json.dumps({"shards": [{"dataset_id": "physical-3", "release_tag": "data-v2-part"}],
        "run_manifest_release_tags_by_release": {"data-v2-part": 123}}))
    with pytest.raises(RuntimeError, match="invalid canonical run manifest tag aliases"):
        _known_tags_from_index(index)

def test_primary_api_exhaustion_stops_without_repeating_requests():
    import pytest
    from download_release_manifests import list_release_manifest_tags
    calls = []
    sleeps = []
    def runner(command, **_kwargs):
        calls.append(command[-1])
        return subprocess.CompletedProcess(
            command, 1, "", "gh: API rate limit exceeded for installation",
        )
    with pytest.raises(RuntimeError, match="allowance exhausted"):
        list_release_manifest_tags(
            "owner/repo", runner=runner, sleeper=sleeps.append, attempts=5,
        )
    assert calls == ["repos/owner/repo/releases?per_page=50&page=1"]
    assert sleeps == []

def test_release_listing_fails_closed_when_full_pages_repeat_forever():
    import json
    import pytest
    from download_release_manifests import list_release_manifest_tags

    calls: list[str] = []
    def runner(command, **_):
        calls.append(command[-1])
        # Broken pagination repeats page 1 at every subsequent offset.
        return subprocess.CompletedProcess(command, 0, json.dumps([
            {"id": 1, "tag_name": "data-v2-one", "assets": []},
            {"id": 2, "tag_name": "data-v2-two", "assets": []},
        ]), "")

    with pytest.raises(RuntimeError, match="pagination made no progress"):
        list_release_manifest_tags("owner/repo", runner=runner, page_size=2)
    assert len(calls) == 3


def test_release_listing_refuses_exhausted_page_budget():
    import json
    import pytest
    from download_release_manifests import list_release_manifest_tags

    calls: list[str] = []
    def runner(command, **_):
        calls.append(command[-1])
        return subprocess.CompletedProcess(command, 0, json.dumps([
            {"id": 1, "tag_name": "data-v2-one", "assets": []},
        ]), "")

    with pytest.raises(RuntimeError, match="page budget exhausted"):
        list_release_manifest_tags("owner/repo", runner=runner, page_size=1, max_pages=1)
    assert len(calls) == 1


def test_reconcile_known_tags_supports_partitioned_index_and_detects_tampering(tmp_path):
    import json
    import pytest
    from download_release_manifests import _known_tags_from_index
    from partitioned_data_index import partition_index

    original = {
        "schema": "alina.data_index.v2",
        "run_manifest_release_tags_by_release": {"data-v2-physical": "data-v2-control"},
        "shards": [{"dataset_id": "shard-one", "release_tag": "data-v2-physical"}],
    }
    root, parts = partition_index(original)
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    index_path = catalog / "DATA_INDEX.json"
    index_path.write_text(json.dumps(root), encoding="utf-8")
    for name, content in parts.items():
        target = catalog / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    assert _known_tags_from_index(index_path) == {"data-v2-control"}
    first = catalog / next(iter(parts))
    first.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="PARTITION_PARITY_(SIZE|DIGEST)_MISMATCH"):
        _known_tags_from_index(index_path)
