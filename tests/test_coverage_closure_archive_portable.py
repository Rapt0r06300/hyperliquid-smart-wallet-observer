from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import hl_observer.ops.archive_portable as archive


def test_folder_exclusion_and_relative_path_validation() -> None:
    assert archive._composant_dossier_exclu("__pycache__")
    assert archive._composant_dossier_exclu(".portable-work")
    assert not archive._composant_dossier_exclu("src")

    assert archive.valider_chemin_relatif("src/a.py") == "src/a.py"
    bad = (
        "",
        "/abs/x",
        "C:/x",
        "a/../b",
        "a//b",
        "a/./b",
        "CON.txt",
        "a?.txt",
        "name. ",
        "x" * 241,
    )
    for rel in bad:
        with pytest.raises(archive.ArchiveRefuseeError):
            archive.valider_chemin_relatif(rel)
    with pytest.raises(archive.ArchiveRefuseeError, match="chemin trop long"):
        archive.valider_chemin_relatif("a/" + "b" * 30, max_rel=10)


def test_private_key_reparse_and_source_validation(tmp_path) -> None:
    key = tmp_path / "key.pem"
    key.write_bytes(
        b"-----BEGIN PRIVATE KEY-----\n" + b"A" * 128 + b"\n-----END PRIVATE KEY-----"
    )
    assert archive.contient_cle_privee(key)
    assert not archive.contient_cle_privee(tmp_path / "missing")

    normal = tmp_path / "normal.txt"
    normal.write_text("ok", encoding="utf-8")
    assert archive._est_reparse(normal) is False
    assert archive.valider_fichier_source(tmp_path, normal) == "normal.txt"
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(archive.ArchiveRefuseeError, match="hors racine"):
        archive.valider_fichier_source(tmp_path, outside)

    link = tmp_path / "link.txt"
    try:
        link.symlink_to(normal)
    except OSError:
        return
    assert archive._est_reparse(link)
    with pytest.raises(archive.ArchiveRefuseeError, match="reparse"):
        archive.valider_fichier_source(tmp_path, link)


def test_sqlite_checkpoint_and_backup_success_and_failure(tmp_path) -> None:
    db = tmp_path / "source.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table t(x integer)")
    con.execute("insert into t values (1)")
    con.commit(); con.close()
    row = archive.checkpoint_wal_sqlite(db)
    assert row == {"base": "source.sqlite", "ok": True}
    dest = tmp_path / "nested" / "copy.sqlite"
    row = archive.copier_sqlite_vers_staging(db, dest)
    assert row["ok"] is True and row["methode"] == "sqlite_backup_api"
    con = sqlite3.connect(dest)
    assert con.execute("select x from t").fetchone()[0] == 1
    con.close()
    failed = archive.copier_sqlite_vers_staging(tmp_path / "missing.sqlite", tmp_path / "bad.sqlite")
    assert failed["ok"] is False
    assert not (tmp_path / "bad.sqlite").exists()


def test_exclusion_policy_and_directory_pruning() -> None:
    excluded = (
        "runtime/foo.json",
        "logs/a.txt",
        "x.pyc",
        "secret.key",
        ".env",
        ".env.local",
        "archive.zip",
        "tmp.pid",
        "node_modules/a.js",
    )
    for rel in excluded:
        assert archive.est_exclu(rel)
    assert not archive.est_exclu("runtime/data/sessions/run/a.json")
    assert not archive.est_exclu("tests/fixtures/a.zip")
    assert not archive.est_exclu("tools/python/python311.zip")
    assert archive._dossier_a_elaguer("runtime/other")
    assert archive._dossier_a_elaguer("logs")
    assert not archive._dossier_a_elaguer("runtime")
    assert not archive._dossier_a_elaguer("runtime/data")
    assert not archive._dossier_a_elaguer("runtime/data/sessions/run")
    assert not archive._dossier_a_elaguer("")


def test_listing_detects_inclusions_exclusions_private_key_and_case_collision(tmp_path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('x')", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "x.txt").write_text("log", encoding="utf-8")
    inclus, exclus = archive.lister_pour_archive(tmp_path)
    assert "src/a.py" in inclus
    assert any(item.startswith("logs") for item in exclus)

    monkeypatch.setattr(archive, "contient_cle_privee", lambda path: Path(path).name == "secret.txt")
    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    with pytest.raises(archive.ArchiveRefuseeError, match="cle privee"):
        archive.lister_pour_archive(tmp_path)

    (tmp_path / "secret.txt").unlink()
    (tmp_path / "A.txt").write_text("a", encoding="utf-8")
    (tmp_path / "a.txt").write_text("b", encoding="utf-8")
    with pytest.raises(archive.ArchiveRefuseeError, match="collision Windows"):
        archive.lister_pour_archive(tmp_path)


def test_metadata_neutralization_and_absolute_residuals(tmp_path) -> None:
    root = tmp_path / "Projet"
    root.mkdir()
    text = f"root={root}\nfile={root / 'src' / 'a.py'}"
    transformed, count = archive.neutraliser_metadonnees(text, root)
    assert count >= 1
    assert str(root) not in transformed
    assert archive.chemins_absolus_residuels("C:\\Users\\Flo\\x /home/flo/x")
    assert archive.chemins_absolus_residuels("relative/path") == []
    assert archive._est_metadonnee("a.json")
    assert archive._est_metadonnee("a.txt")
    assert archive._est_metadonnee("a.toml")
    assert not archive._est_metadonnee("a.py")
    assert not archive._est_metadonnee("tools/python/config.json")


def test_git_sha_from_loose_packed_detached_and_missing(tmp_path) -> None:
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text("a" * 40 + "\n", encoding="utf-8")
    assert archive._git_sha_depuis_dossier(tmp_path) == "a" * 40
    (git / "refs" / "heads" / "main").unlink()
    (git / "packed-refs").write_text("b" * 40 + " refs/heads/main\n", encoding="utf-8")
    assert archive._git_sha_depuis_dossier(tmp_path) == "b" * 40
    (git / "HEAD").write_text("c" * 40 + "\n", encoding="utf-8")
    assert archive._git_sha_depuis_dossier(tmp_path) == "c" * 40
    assert archive._git_sha_depuis_dossier(tmp_path / "missing") == ""


def test_git_release_state_clean_dirty_rename_and_invalid(tmp_path, monkeypatch) -> None:
    outputs = iter(["a" * 40 + "\n", "1700000000\n", ""])
    monkeypatch.setattr(archive, "_commande_git", lambda root, *args: next(outputs))
    clean = archive.etat_git_release(tmp_path)
    assert clean["sha"] == "a" * 40 and clean["source_date_epoch"] == 1700000000 and clean["dirty"] is False

    f = tmp_path / "new.txt"; f.write_text("x", encoding="utf-8")
    outputs = iter(["b" * 40 + "\n", "1700000001\n", "?? new.txt\nR  old.txt -> new.txt\n"])
    monkeypatch.setattr(archive, "_commande_git", lambda root, *args: next(outputs))
    dirty = archive.etat_git_release(tmp_path)
    assert dirty["dirty"] is True and len(dirty["fichiers"]) == 2
    assert all(row["chemin"] == "new.txt" for row in dirty["fichiers"])

    outputs = iter(["bad\n"])
    monkeypatch.setattr(archive, "_commande_git", lambda root, *args: next(outputs))
    with pytest.raises(archive.ArchiveRefuseeError, match="SHA Git invalide"):
        archive.etat_git_release(tmp_path)


def test_lfs_binary_categories_version_deps_licenses_and_sbom(tmp_path) -> None:
    normal = tmp_path / "normal.bin"; normal.write_bytes(b"data")
    lfs = tmp_path / "pointer.bin"; lfs.write_bytes(archive._MARQUEUR_LFS + b"\noid sha256:x")
    assert archive.pointeurs_lfs_non_materialises(tmp_path, ["normal.bin", "pointer.bin", "missing.bin"]) == ["pointer.bin"]
    assert archive._categorie_binaire("a.whl") == "wheel"
    assert archive._categorie_binaire("a.dll") == "dll"
    assert archive._categorie_binaire("a.pyd") == "dll"
    assert archive._categorie_binaire("a.exe") == "exe"
    assert archive._categorie_binaire("a.py") is None

    assert archive._version_projet(tmp_path) == "0.0.0-dev"
    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    assert archive._version_projet(tmp_path) == "1.2.3"
    (tmp_path / "requirements.lock").write_text("# c\na==1\n\nb==2\n", encoding="utf-8")
    assert archive._deps_verrouillees(tmp_path) == ["a==1", "b==2"]
    (tmp_path / "LICENSE").write_text("license", encoding="utf-8")
    (tmp_path / "NOTICE.txt").write_text("notice", encoding="utf-8")
    assert archive._licences(tmp_path) == ["LICENSE", "NOTICE.txt"]
    (tmp_path / "LANCER_HYPERSMART.cmd").write_text("", encoding="utf-8")
    files = {"a.py": {}, "x.whl": {}, "y.dll": {}, "z.exe": {}}
    binaries = {
        "x.whl": {"categorie": "wheel"},
        "y.dll": {"categorie": "dll"},
        "z.exe": {"categorie": "exe"},
    }
    sbom = archive._sbom(tmp_path, files, binaries)
    assert sbom["modules_python"] == 1 and sbom["wheels"] == 1 and sbom["dll"] == 1 and sbom["exe"] == 1
    assert "LICENSE" in sbom["licences"]
    assert "LANCER_HYPERSMART.cmd" in sbom["cmd_maitres"]


def test_manifest_build_and_fingerprint(tmp_path, monkeypatch) -> None:
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / "tool.exe").write_bytes(b"exe")
    monkeypatch.setattr(archive.SC, "scanner_sessions", lambda root: [
        {"run_id": "ok", "statut": archive.SC.STATUT_COMPLETE},
        {"run_id": "q", "statut": archive.SC.STATUT_QUARANTINED},
        {"run_id": "active", "statut": archive.SC.STATUT_ACTIVE},
    ])
    manifest = archive.construire_manifeste(
        tmp_path, ["a.py", "tool.exe"], ["x"], version="9.9", git_sha="f" * 40,
        source_date_epoch=1700000000, etat_git={"dirty": False},
    )
    assert manifest["schema"] == archive.SCHEMA_MANIFESTE
    assert manifest["hypersmart_version"] == "9.9"
    assert manifest["git_sha"] == "f" * 40
    assert manifest["nombre_fichiers"] == 2
    assert manifest["donnees_incluses"] == ["ok", "q"]
    assert manifest["binaires"]["tool.exe"]["categorie"] == "exe"
    assert len(manifest["empreinte_globale"]) == 64
    assert archive._empreinte_manifeste(manifest["fichiers"]) == manifest["empreinte_globale"]


def test_zip_validation_safe_extract_and_reverify(tmp_path) -> None:
    root = tmp_path / "root"; root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")
    manifest = archive.construire_manifeste(root, ["a.txt"], [], version="1", git_sha="a" * 40, source_date_epoch=1700000000)
    target = tmp_path / "portable.zip"
    result = archive.ecrire_archive(root, target, ["a.txt"], manifest)
    assert result["membres"] == 2 and result["source_date_epoch"] == 1700000000
    assert archive.reverifier_archive(target)["ok"] is True
    extracted = tmp_path / "extract"
    result = archive.extraire_et_reverifier(target, dossier_extraction=extracted)
    assert result["ok"] is True and result["verifies"] == 1
    assert (extracted / "a.txt").read_text(encoding="utf-8") == "hello"

    with zipfile.ZipFile(target) as z:
        path_check = archive.valider_membres_zip(z, longueur_base=10)
        assert path_check["membres"] == 2

    missing_manifest = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(missing_manifest, "w") as z:
        z.writestr("a.txt", "x")
    assert archive.reverifier_archive(missing_manifest) == {"ok": False, "raison": "MANIFESTE_ABSENT"}
    assert archive.extraire_et_reverifier(missing_manifest) == {"ok": False, "raison": "MANIFESTE_ABSENT"}


def test_zip_refuses_case_collision_symlink_and_long_path(tmp_path) -> None:
    collision = tmp_path / "collision.zip"
    with zipfile.ZipFile(collision, "w") as z:
        z.writestr("A.txt", "a")
        z.writestr("a.txt", "b")
    with zipfile.ZipFile(collision) as z:
        with pytest.raises(archive.ArchiveRefuseeError, match="collision Windows"):
            archive.valider_membres_zip(z)

    symlink_zip = tmp_path / "link.zip"
    with zipfile.ZipFile(symlink_zip, "w") as z:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, "target")
    with zipfile.ZipFile(symlink_zip) as z:
        with pytest.raises(archive.ArchiveRefuseeError, match="lien symbolique"):
            archive.valider_membres_zip(z)

    long_zip = tmp_path / "long.zip"
    with zipfile.ZipFile(long_zip, "w") as z:
        z.writestr("x" * 200 + ".txt", "x")
    with zipfile.ZipFile(long_zip) as z:
        with pytest.raises(archive.ArchiveRefuseeError, match="incompatible Windows"):
            archive.valider_membres_zip(z, longueur_base=100)


def test_build_staging_regular_metadata_sqlite_and_cleanup(tmp_path, monkeypatch) -> None:
    root = tmp_path / "source"; root.mkdir()
    (root / "regular.bin").write_bytes(b"abc")
    (root / "meta.json").write_text(json.dumps({"path": str(root / "x")}), encoding="utf-8")
    db = root / "db.sqlite"
    con = sqlite3.connect(db); con.execute("create table t(x)"); con.commit(); con.close()
    staging = tmp_path / "stage"
    result = archive.construire_staging(root, staging, ["regular.bin", "meta.json", "db.sqlite"])
    assert result["fichiers"] == ["db.sqlite", "meta.json", "regular.bin"]
    assert result["sqlite"][0]["ok"] is True
    assert result["chemins_neutralises"] >= 1
    assert str(root) not in (staging / "meta.json").read_text(encoding="utf-8")

    inner = root / "inner"
    with pytest.raises(archive.ArchiveRefuseeError, match="staging doit etre exterieur"):
        archive.construire_staging(root, inner, ["regular.bin"])

    monkeypatch.setattr(archive, "copier_sqlite_vers_staging", lambda src, dst: {"ok": False, "base": "db"})
    failed_stage = tmp_path / "failed"
    with pytest.raises(archive.ArchiveRefuseeError, match="copie SQLite impossible"):
        archive.construire_staging(root, failed_stage, ["db.sqlite"])
    assert not failed_stage.exists()


def test_preparer_sqlite_skips_excluded_directories(tmp_path, monkeypatch) -> None:
    (tmp_path / "good.sqlite").write_bytes(b"")
    excluded = tmp_path / "__pycache__"; excluded.mkdir()
    (excluded / "bad.sqlite").write_bytes(b"")
    seen = []
    monkeypatch.setattr(archive, "checkpoint_wal_sqlite", lambda path: (seen.append(Path(path).name) or {"base": Path(path).name, "ok": True}))
    rows = archive.preparer_sqlite(tmp_path)
    assert [row["base"] for row in rows] == ["good.sqlite"]
    assert seen == ["good.sqlite"]
