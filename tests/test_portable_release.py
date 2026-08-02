"""Atomic portable release orchestration and fail-closed publication."""
from __future__ import annotations

from pathlib import Path

import pytest

from hl_observer.ops import portable_release as PR
from hl_observer.ops.archive_portable import ArchiveRefuseeError


def _git_clean():
    return {"sha": "d" * 40, "dirty": False, "fichiers": [], "source_date_epoch": 1_700_000_000}


def _builder(root, target, **_kwargs):
    Path(target).write_bytes(b"deterministic-zip")
    return {"archive": str(target), "exclus": 0}


def _validator(_archive, *, archive_repetition, extraction_parent, **_kwargs):
    extracted = Path(extraction_parent) / "simple"
    extracted.mkdir(parents=True)
    return {
        "schema": "hypersmart.portable_validation.v1", "ok": True,
        "checks": {}, "archive_sha256": "x", "git_sha": "d" * 40,
        "manifest_fingerprint": "f", "paper_read_only": True, "real_execution": False,
        "repeat_exists": Path(archive_repetition).is_file(),
    }


def _ready(_root, *, preuve):
    return {"RELEASE_READY": Path(preuve).is_file(), "manquants": [], "gates": []}


def _artifacts(archive, **_kwargs):
    return {"ok": Path(archive).is_file()}


def test_release_is_only_published_after_two_builds_and_validation(tmp_path, monkeypatch):
    root = tmp_path / "project"
    output = tmp_path / "desktop"
    root.mkdir()
    monkeypatch.setattr(PR, "etat_git_release", lambda _root: _git_clean())
    monkeypatch.setattr(PR, "_version_projet", lambda _root: "1.2.3")
    result = PR.creer_release_portable(
        root, output_directory=output, archive_builder=_builder, validator=_validator,
        ready_evaluator=_ready, artifact_writer=_artifacts,
    )
    archive = Path(result["archive"])
    assert result["RELEASE_READY"] is True
    assert archive.parent == output and archive.read_bytes() == b"deterministic-zip"
    assert result["validation"]["repeat_exists"] is True
    assert not list(output.glob(".*.tmp"))


def test_failed_release_keeps_no_candidate_zip(tmp_path, monkeypatch):
    root = tmp_path / "project"
    output = tmp_path / "desktop"
    root.mkdir()
    monkeypatch.setattr(PR, "etat_git_release", lambda _root: _git_clean())
    monkeypatch.setattr(PR, "_version_projet", lambda _root: "1.2.3")

    def not_ready(_root, *, preuve):
        return {"RELEASE_READY": False, "manquants": ["ci_head_verte"], "gates": []}

    with pytest.raises(ArchiveRefuseeError, match="RELEASE_READY=false"):
        PR.creer_release_portable(
            root, output_directory=output, archive_builder=_builder, validator=_validator,
            ready_evaluator=not_ready, artifact_writer=_artifacts,
        )
    assert not list(output.glob("*.zip"))
    assert (output / "RELEASE_FAILED.json").is_file()


def test_output_directory_inside_project_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(PR, "etat_git_release", lambda _root: _git_clean())
    with pytest.raises(ArchiveRefuseeError, match="outside project"):
        PR.creer_release_portable(root, output_directory=root / "dist")
