from __future__ import annotations

import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "restore_alina_resource_limits_test", ROOT / "tools" / "restore_alina.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _receipt(module, result: dict) -> dict:
    payload = result["payload"]
    return {
        "evidence_tag": "limits-test",
        "kind": "replay",
        "result_sha256": module._canonical_json_sha256(result),
        "payload_digest": module._canonical_json_sha256(payload),
    }


def _write_result_tar(path: Path, *, extra: tuple[str, bytes] | None = None) -> dict:
    result = {"status": "COMPLETE", "payload": {"net_usd": 0.0}}
    with tarfile.open(path, "w:gz") as archive:
        payload = json.dumps(result, sort_keys=True).encode("utf-8")
        info = tarfile.TarInfo("result.json")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
        if extra is not None:
            name, data = extra
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return result


def test_zip_member_count_limit_is_fail_closed(tmp_path, monkeypatch):
    module = _module()
    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as handle:
        handle.writestr("one.json", b"1")
        handle.writestr("two.json", b"2")
    monkeypatch.setattr(module, "MAX_ARCHIVE_MEMBERS", 1)

    with pytest.raises(module.RestoreError, match="member_count=2"):
        module._verify_zip_archive(archive, archive.name)


def test_zip_declared_expansion_limit_is_checked_before_payload_read(tmp_path, monkeypatch):
    module = _module()
    archive = tmp_path / "expanded.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as handle:
        handle.writestr("payload.json", b"12")
    monkeypatch.setattr(module, "MAX_ARCHIVE_DECLARED_BYTES", 1)

    with pytest.raises(module.RestoreError, match="declared_bytes=2"):
        module._verify_zip_archive(archive, archive.name)


def test_zip_nested_archive_is_not_admitted(tmp_path):
    module = _module()
    archive = tmp_path / "nested.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as handle:
        handle.writestr("inner.zip", b"not-a-second-archive")

    with pytest.raises(module.RestoreError, match="archive_nesting_depth=2"):
        module._verify_zip_archive(archive, archive.name)


def test_compressed_archive_size_limit_is_checked_before_open(tmp_path, monkeypatch):
    module = _module()
    archive = tmp_path / "bounded.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.json", b"payload")
    monkeypatch.setattr(module, "MAX_ARCHIVE_BYTES", archive.stat().st_size - 1)

    with pytest.raises(module.RestoreError, match="compressed_bytes="):
        module._verify_zip_archive(archive, archive.name)


def test_tar_member_count_limit_removes_partial_materialization(tmp_path, monkeypatch):
    module = _module()
    archive = tmp_path / "many.tgz"
    result = _write_result_tar(archive, extra=("extra.json", b"x"))
    monkeypatch.setattr(module, "MAX_ARCHIVE_MEMBERS", 1)

    with pytest.raises(module.RestoreError, match="member_count=2"):
        module.materialize_analysis_evidence(
            archive, _receipt(module, result), tmp_path / "usable"
        )
    assert not list((tmp_path / "usable").rglob("CERTIFIED_EVIDENCE.json"))


def test_tar_declared_size_limit_is_fail_closed(tmp_path, monkeypatch):
    module = _module()
    archive = tmp_path / "large.tgz"
    result = _write_result_tar(archive)
    monkeypatch.setattr(module, "MAX_ARCHIVE_DECLARED_BYTES", 1)

    with pytest.raises(module.RestoreError, match="declared_bytes="):
        module.materialize_analysis_evidence(
            archive, _receipt(module, result), tmp_path / "usable"
        )


def test_tar_materialization_is_streaming_and_receipts_limits(tmp_path, monkeypatch):
    module = _module()
    archive = tmp_path / "streamed.tgz"
    result = _write_result_tar(archive)

    def fail_getmembers(_self):
        raise AssertionError("streaming materialization must not call getmembers")

    monkeypatch.setattr(tarfile.TarFile, "getmembers", fail_getmembers)
    restored = module.materialize_analysis_evidence(
        archive, _receipt(module, result), tmp_path / "usable"
    )

    assert restored["status"] == "VERIFIED"
    proof = next((tmp_path / "usable").rglob("CERTIFIED_EVIDENCE.json"))
    payload = json.loads(proof.read_text(encoding="utf-8"))
    assert payload["archive_limits"]["schema"] == module.ARCHIVE_LIMITS_SCHEMA
    assert payload["archive_limits"]["max_members"] == module.MAX_ARCHIVE_MEMBERS

