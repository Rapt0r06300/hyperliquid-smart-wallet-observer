from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.ops import release_ready as RR


def test_load_json_rejects_non_object_root(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON root must be an object"):
        RR._load_json(path)


def test_load_wheel_verifier_rejects_unloadable_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = tmp_path / "tools" / "wheelhouse_lock.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("# synthetic verifier\n", encoding="utf-8")
    monkeypatch.setattr(RR.importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: None)

    assert RR._load_wheel_verifier(tmp_path) is None


def test_wheelhouse_verifier_exception_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheelhouse = tmp_path / "tools" / "wheelhouse"
    wheelhouse.mkdir(parents=True)
    (wheelhouse / "WHEELHOUSE_LOCK.json").write_text("{}", encoding="utf-8")
    (tmp_path / "requirements-portable.txt").write_text("locked", encoding="utf-8")

    def fail_verifier(*_args: object) -> dict[str, object]:
        raise RuntimeError("synthetic verifier failure")

    monkeypatch.setattr(RR, "_load_wheel_verifier", lambda _root: fail_verifier)
    gate = RR._wheelhouse(tmp_path)

    assert gate["ok"] is False
    assert "synthetic verifier failure" in gate["detail"]


def test_manifest_rejects_invalid_schema_and_missing_member(tmp_path: Path) -> None:
    manifest_path = tmp_path / RR.NOM_MANIFESTE
    invalid = {
        "schema": "wrong.schema",
        "git_sha": "a" * 40,
        "empreinte_globale": "irrelevant",
        "fichiers": {"src/app.py": {"sha256": "0" * 64, "taille": 1}},
    }
    manifest_path.write_text(json.dumps(invalid), encoding="utf-8")
    _manifest, gate = RR._manifest(tmp_path)
    assert gate["ok"] is False
    assert gate["detail"] == "schema/files invalid"

    files = {"src/missing.py": {"sha256": "0" * 64, "taille": 1}}
    missing = {
        "schema": RR.SCHEMA_MANIFESTE,
        "git_sha": "a" * 40,
        "empreinte_globale": RR._manifest_fingerprint(files),
        "fichiers": files,
    }
    manifest_path.write_text(json.dumps(missing), encoding="utf-8")
    _manifest, gate = RR._manifest(tmp_path)
    assert gate["ok"] is False
    assert "missing=1" in gate["detail"]


def test_evidence_rejects_wrong_schema(tmp_path: Path) -> None:
    path = tmp_path / "PORTABLE_VALIDATION.json"
    path.write_text(json.dumps({"schema": "wrong.schema"}), encoding="utf-8")

    payload, detail = RR._evidence(path)

    assert payload == {}
    assert detail == "validation evidence schema invalid"
