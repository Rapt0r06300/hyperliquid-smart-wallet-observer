from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
import zipfile
from pathlib import Path

import pytest

import hl_observer.ops.archive_portable as archive


def test_relative_paths_exclusion_and_private_key(tmp_path) -> None:
    assert archive.valider_chemin_relatif("src/a.py") == "src/a.py"
    for rel in ("", "/abs/x", "C:/x", "a/../b", "a//b", "CON.txt", "a?.txt"):
        with pytest.raises(archive.ArchiveRefuseeError):
            archive.valider_chemin_relatif(rel)
    assert archive.est_exclu("runtime/foo.json") is True
    assert archive.est_exclu("runtime/data/sessions/run/a.json") is False
    assert archive.est_exclu("tests/fixtures/a.zip") is False

    key = tmp_path / "key.pem"
    key.write_bytes(
        b"-----BEGIN PRIVATE KEY-----\n" + b"A" * 128 + b"\n-----END PRIVATE KEY-----"
    )
    assert archive.contient_cle_privee(key) is True
    assert archive.contient_cle_privee(tmp_path / "missing") is False


def test_sqlite_backup_and_staging(tmp_path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    db = root / "db.sqlite"
    connection = sqlite3.connect(db)
    connection.execute("create table t(x integer)")
    connection.execute("insert into t values (1)")
    connection.commit()
    connection.close()

    copied = tmp_path / "copy.sqlite"
    row = archive.copier_sqlite_vers_staging(db, copied)
    assert row["ok"] is True and row["methode"] == "sqlite_backup_api"
    check = sqlite3.connect(copied)
    assert check.execute("select x from t").fetchone()[0] == 1
    check.close()

    (root / "regular.bin").write_bytes(b"abc")
    (root / "meta.json").write_text(
        json.dumps({"path": str(root / "x")}),
        encoding="utf-8",
    )
    staging = tmp_path / "stage"
    result = archive.construire_staging(
        root,
        staging,
        ["regular.bin", "meta.json", "db.sqlite"],
    )
    assert result["fichiers"] == ["db.sqlite", "meta.json", "regular.bin"]
    assert result["sqlite"][0]["ok"] is True
    assert str(root) not in (staging / "meta.json").read_text(encoding="utf-8")


def test_manifest_zip_round_trip_and_fail_closed(tmp_path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(archive.SC, "scanner_sessions", lambda root: [])
    manifest = archive.construire_manifeste(
        root,
        ["a.txt"],
        [],
        version="1",
        git_sha="a" * 40,
        source_date_epoch=1700000000,
    )
    assert manifest["schema"] == archive.SCHEMA_MANIFESTE
    assert manifest["nombre_fichiers"] == 1
    assert len(manifest["empreinte_globale"]) == 64
    assert archive._empreinte_manifeste(manifest["fichiers"]) == manifest["empreinte_globale"]

    target = tmp_path / "portable.zip"
    archive.ecrire_archive(root, target, ["a.txt"], manifest)
    assert archive.reverifier_archive(target)["ok"] is True
    extracted = tmp_path / "extract"
    result = archive.extraire_et_reverifier(target, dossier_extraction=extracted)
    assert result["ok"] is True and result["verifies"] == 1
    assert (extracted / "a.txt").read_text(encoding="utf-8") == "hello"

    missing = tmp_path / "missing-manifest.zip"
    with zipfile.ZipFile(missing, "w") as bundle:
        bundle.writestr("a.txt", "x")
    assert archive.reverifier_archive(missing) == {"ok": False, "raison": "MANIFESTE_ABSENT"}


def test_zip_security_collision_symlink_and_hash(tmp_path) -> None:
    collision = tmp_path / "collision.zip"
    with zipfile.ZipFile(collision, "w") as bundle:
        bundle.writestr("A.txt", "a")
        bundle.writestr("a.txt", "b")
    with zipfile.ZipFile(collision) as bundle:
        with pytest.raises(archive.ArchiveRefuseeError, match="collision Windows"):
            archive.valider_membres_zip(bundle)

    symlink = tmp_path / "symlink.zip"
    with zipfile.ZipFile(symlink, "w") as bundle:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(info, "target")
    with zipfile.ZipFile(symlink) as bundle:
        with pytest.raises(archive.ArchiveRefuseeError, match="lien symbolique"):
            archive.valider_membres_zip(bundle)

    data = b"abc"
    assert hashlib.sha256(data).hexdigest() == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_git_sha_lfs_and_metadata_helpers(tmp_path) -> None:
    git = tmp_path / ".git" / "refs" / "heads"
    git.mkdir(parents=True)
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "main").write_text("a" * 40 + "\n", encoding="utf-8")
    assert archive._git_sha_depuis_dossier(tmp_path) == "a" * 40

    pointer = tmp_path / "pointer.bin"
    pointer.write_bytes(archive._MARQUEUR_LFS + b"\noid sha256:x")
    assert archive.pointeurs_lfs_non_materialises(tmp_path, ["pointer.bin"]) == ["pointer.bin"]

    project = tmp_path / "Projet"
    project.mkdir()
    transformed, count = archive.neutraliser_metadonnees(
        f"root={project}\nfile={project / 'src' / 'a.py'}",
        project,
    )
    assert count >= 1 and str(project) not in transformed
    assert archive.chemins_absolus_residuels("relative/path") == []
    assert archive._categorie_binaire("a.whl") == "wheel"
    assert archive._categorie_binaire("a.dll") == "dll"
    assert archive._categorie_binaire("a.exe") == "exe"
    assert archive._categorie_binaire("a.py") is None
