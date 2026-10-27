import hashlib
import json
import zipfile

from tools.package_okx_observations import build_archive


def test_archive_contains_hash_bound_research_only_manifest(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    source = reports / "selection.json"
    source.write_text('{"tracked": []}\n', encoding="utf-8")
    archive_path = tmp_path / "observations.zip"
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")

    manifest = build_archive(reports, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ["selection.json", "MANIFEST.json"]
        stored_manifest = json.loads(archive.read("MANIFEST.json"))
    assert manifest == stored_manifest
    assert stored_manifest["research_only"] is True
    assert stored_manifest["safe_replay_evidence"] is False
    assert stored_manifest["files"] == [{
        "path": "selection.json",
        "size_bytes": len(source.read_bytes()),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }]
