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

