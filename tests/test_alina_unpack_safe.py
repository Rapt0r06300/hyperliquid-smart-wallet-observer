from __future__ import annotations

import collections
import gzip
import hashlib
import json
from pathlib import Path

import pytest
import tools.unpack_verified_safe as unpack_module
from tools.restore_alina import _windows_io_path as canonical_windows_io_path
from tools.unpack_verified_safe import SafeUnpackError, expand_safe_corpus


def fixture(root):
    path = root / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    path.parent.mkdir(parents=True)
    canonical_windows_io_path(path).write_bytes(gzip.compress(b'{"px":100}\n', mtime=0))
    _bind_catalog(root, path, "safe")


def _digest(root):
    return hashlib.sha256((root / "catalog" / "DATA_INDEX.json").read_bytes()).hexdigest()


def _bind_catalog(root, source, dataset_id):
    index = root / "catalog" / "DATA_INDEX.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    canonical_windows_io_path(index).write_text(json.dumps({
        "schema": "alina.data_index.v2",
        "shards": [{
            "dataset_id": dataset_id,
            "family": "trades",
            "release_tag": source.parent.name,
            "release_asset": source.name,
            "quality_status": "SAFE",
            "replay_compatible": True,
            "sha256": hashlib.sha256(canonical_windows_io_path(source).read_bytes()).hexdigest(),
            "bytes": canonical_windows_io_path(source).stat().st_size,
        }],
    }), encoding="utf-8")
    canonical_windows_io_path(root / "RESTORE_REPORT.json").write_text(json.dumps({
        "status": "REPLAY_READY_COMPLETE",
        "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "classification": {"materialization_complete": True, "usable_shards": 1},
        "catalog_verification": {"source_index_sha256": _digest(root)},
    }), encoding="utf-8")



def _disque_insuffisant(monkeypatch):
    """Fait croire a 1 Ko de libre : la place manque, comme sur la machine reelle."""
    import shutil
    Usage = collections.namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: Usage(10**12, 10**12, 1024))


def test_sans_place_on_bascule_en_SCEAU_SEUL_au_lieu_de_refuser(tmp_path, monkeypatch, capsys):
    """LE cul-de-sac repare (20/11/2026).

    Extraire le corpus reel reclame 2,31 To quand la machine en offre 705 Go. Refuser
    laissait 1 792 577 shards INVISIBLES au labo, sans qu aucune action de l operateur ne
    puisse y changer quoi que ce soit. On bascule desormais en sceau seul : toutes les
    preuves sont conservees, seul le JSONL n est pas ecrit -- le pont le relit en flux.
    """
    fixture(tmp_path)
    _disque_insuffisant(monkeypatch)

    rapport = _expand(tmp_path)

    assert rapport["status"] == "SAFE_UNPACK_COMPLETE"
    assert rapport["mode"] == "SEAL_ONLY"
    assert "ALINA_UNPACK_SEAL_ONLY_FALLBACK" in capsys.readouterr().err


def test_la_bascule_ecrit_le_sceau_mais_PAS_le_jsonl(tmp_path, monkeypatch):
    fixture(tmp_path)
    _disque_insuffisant(monkeypatch)
    _expand(tmp_path)
    dossier = tmp_path / "usable" / "unpacked" / "release-one"
    assert (dossier / "safe.jsonl.alina.json").is_file(), "le sceau doit exister"
    assert not (dossier / "safe.jsonl").exists(), "le JSONL ne doit PAS etre ecrit"


def test_le_sceau_de_la_bascule_porte_les_MEMES_preuves(tmp_path, monkeypatch, tmp_path_factory):
    """Le sceau doit etre identique a celui du mode complet : sinon la preuve differe."""
    complet = tmp_path_factory.mktemp("complet")
    fixture(complet)
    _expand(complet)
    ref = json.loads((complet / "usable" / "unpacked" / "release-one"
                      / "safe.jsonl.alina.json").read_text(encoding="utf-8"))

    fixture(tmp_path)
    _disque_insuffisant(monkeypatch)
    _expand(tmp_path)
    sceau = json.loads((tmp_path / "usable" / "unpacked" / "release-one"
                        / "safe.jsonl.alina.json").read_text(encoding="utf-8"))

    assert sceau == ref, "le sceau du mode sceau seul doit etre identique au mode complet"


def test_la_reprise_en_sceau_seul_ne_met_PAS_le_sceau_en_quarantaine(tmp_path, monkeypatch):
    """Un sceau sans son JSONL est NORMAL ici ; le code l aurait mis en quarantaine."""
    fixture(tmp_path)
    _disque_insuffisant(monkeypatch)
    _expand(tmp_path)
    rapport = _expand(tmp_path)   # second passage : il doit REUTILISER
    assert rapport["status"] == "SAFE_UNPACK_COMPLETE"
    quarantaine = tmp_path / "quarantine"
    orphelins = [f for f in quarantaine.rglob("*") if f.is_file()] if quarantaine.exists() else []
    assert not orphelins, f"le sceau a ete mis en quarantaine : {orphelins}"
    assert rapport["reused_verified"] >= 1, "le second passage doit REUTILISER le sceau"
    assert rapport["quarantined_unsealed_outputs"] == 0
    assert rapport["certified_shards"] >= 1

def _expand(root, *, catalog_sha256=None):
    return expand_safe_corpus(
        root,
        catalog_sha256=catalog_sha256 if catalog_sha256 is not None else _digest(root),
        catalog_path=root / "catalog" / "DATA_INDEX.json",
    )


def test_unpacked_safe_is_verified_and_resumable(tmp_path):
    fixture(tmp_path)
    report = _expand(tmp_path)
    target = tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl"
    assert report["status"] == "SAFE_UNPACK_COMPLETE"
    assert target.read_bytes() == b'{"px":100}\n'
    assert _expand(tmp_path)["reused_verified"] == 1
    seal = json.loads(target.with_suffix(".jsonl.alina.json").read_text())
    assert seal["jsonl_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()


def test_copy_vault_only_unpack_ignores_and_preserves_other_safe_families(tmp_path):
    selected = tmp_path / "usable" / "shards" / "cv-release" / "cv.jsonl.gz"
    unrelated = tmp_path / "usable" / "shards" / "other-release" / "trades.jsonl.gz"
    selected.parent.mkdir(parents=True)
    unrelated.parent.mkdir(parents=True)
    selected.write_bytes(gzip.compress(b'{"copy_vault":true}\n', mtime=0))
    unrelated.write_bytes(gzip.compress(b'{"other":true}\n', mtime=0))
    rows = []
    for dataset_id, family, source in (
        ("cv", "copy_vault_fills", selected),
        ("other", "trades", unrelated),
    ):
        rows.append({
            "dataset_id": dataset_id,
            "family": family,
            "release_tag": source.parent.name,
            "release_asset": source.name,
            "quality_status": "SAFE",
            "replay_compatible": True,
            "sha256": hashlib.sha256(canonical_windows_io_path(source).read_bytes()).hexdigest(),
            "bytes": canonical_windows_io_path(source).stat().st_size,
        })
    index = tmp_path / "catalog" / "DATA_INDEX.json"
    index.parent.mkdir(parents=True)
    canonical_windows_io_path(index).write_text(
        json.dumps({"schema": "alina.data_index.v2", "shards": rows}),
        encoding="utf-8",
    )
    digest = _digest(tmp_path)
    canonical_windows_io_path(tmp_path / "RESTORE_REPORT.json").write_text(json.dumps({
        "status": "REPLAY_READY_COMPLETE",
        "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "selection_scope": "COPY_VAULT_ONLY",
        "selection_families": ["copy_vault_fills"],
        "classification": {"materialization_complete": True, "usable_shards": 1},
        "catalog_verification": {
            "source_index_sha256": digest,
            "selection_scope": "COPY_VAULT_ONLY",
            "selection_families": ["copy_vault_fills"],
        },
    }), encoding="utf-8")

    report = _expand(tmp_path)

    assert report["status"] == "SAFE_UNPACK_COMPLETE"
    assert report["selection_scope"] == "COPY_VAULT_ONLY"
    assert report["selection_families"] == ["copy_vault_fills"]
    assert report["certified_shards"] == 1
    assert (tmp_path / "usable" / "unpacked" / "cv-release" / "cv.jsonl").is_file()
    assert not (tmp_path / "usable" / "unpacked" / "other-release" / "trades.jsonl").exists()
    assert unrelated.is_file()


def test_tampered_unpacked_shard_fails_closed(tmp_path):
    fixture(tmp_path)
    with pytest.raises(SafeUnpackError, match="not certified"):
        _expand(tmp_path, catalog_sha256="b" * 64)
    _expand(tmp_path)
    target = tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl"
    target.write_text("corrupt\n", encoding="utf-8")
    with pytest.raises(SafeUnpackError, match="changed"):
        _expand(tmp_path)
    assert json.loads((tmp_path / "UNPACK_REPORT.json").read_text())["status"] != "SAFE_UNPACK_COMPLETE"


def test_bad_gzip_does_not_produce_complete_report(tmp_path):
    fixture(tmp_path)
    path = tmp_path / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    damaged = bytearray(path.read_bytes())
    damaged[-8] ^= 17
    path.write_bytes(damaged)
    with pytest.raises((SafeUnpackError, gzip.BadGzipFile, OSError)):
        _expand(tmp_path)
    assert json.loads((tmp_path / "UNPACK_REPORT.json").read_text())["status"] != "SAFE_UNPACK_COMPLETE"


def test_unpack_flag_requires_explicit_safe_download():
    from tools.sync_complete_clone import main
    assert main(["--unpack-safe"]) == 2


def test_unselected_prior_jsonl_is_quarantined_not_mixed_or_deleted(tmp_path):
    fixture(tmp_path)
    _expand(tmp_path)
    old = tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl"
    source = tmp_path / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    source.unlink()
    new = source.parent / "new.jsonl.gz"
    new.write_bytes(gzip.compress(b'{"px":200}\n', mtime=0))
    _bind_catalog(tmp_path, new, "new")
    outcome = _expand(tmp_path)
    assert outcome["quarantined_stale_outputs"] == 1
    assert not old.exists()
    assert list((tmp_path / "quarantine" / "stale_unpacked").rglob("*.stale"))
    assert (tmp_path / "usable" / "unpacked" / "release-one" / "new.jsonl").is_file()


def test_valid_gzip_with_invalid_jsonl_is_rejected(tmp_path):
    fixture(tmp_path)
    path = tmp_path / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    path.write_bytes(gzip.compress(b"this-is-not-json\n", mtime=0))
    _bind_catalog(tmp_path, path, "safe")
    with pytest.raises(SafeUnpackError, match="invalid JSONL"):
        _expand(tmp_path)
    assert json.loads((tmp_path / "UNPACK_REPORT.json").read_text())["status"] != "SAFE_UNPACK_COMPLETE"
    assert not (tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl").exists()



def test_interrupted_unsealed_jsonl_quarantined_and_reconstructed(tmp_path):
    fixture(tmp_path)
    target = tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"partial crash output")
    result = _expand(tmp_path)
    assert result["status"] == "SAFE_UNPACK_COMPLETE"
    assert result["quarantined_unsealed_outputs"] == 1
    assert target.read_bytes() == b'{"px":100}\n'
    assert list((tmp_path / "quarantine" / "unsealed_unpacked").rglob("*.unsealed"))


def test_modified_but_valid_gzip_must_not_be_accepted_as_certified_safe(tmp_path):
    fixture(tmp_path)
    source = tmp_path / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    source.write_bytes(gzip.compress(b'{"px":999}\n', mtime=0))
    with pytest.raises(SafeUnpackError, match="SHA-256 changed"):
        _expand(tmp_path)
    assert json.loads((tmp_path / "UNPACK_REPORT.json").read_text())["status"] != "SAFE_UNPACK_COMPLETE"


def test_old_success_report_is_invalidated_on_missing_restore_certificate(tmp_path):
    fixture(tmp_path)
    _expand(tmp_path)
    certificate = tmp_path / "RESTORE_REPORT.json"
    certificate.unlink()
    with pytest.raises(SafeUnpackError, match="missing verified"):
        _expand(tmp_path)
    report = json.loads((tmp_path / "UNPACK_REPORT.json").read_text())
    assert report["status"] == "UNPACK_IN_PROGRESS_NOT_CERTIFIED"



def test_long_release_paths_are_normalized_before_unpack_io(tmp_path, monkeypatch):
    root = tmp_path / "copy-vault"
    release_tag = "r" * 180
    dataset_id = "d" * 180
    source = root / "usable" / "shards" / release_tag / f"{dataset_id}.jsonl.gz"
    canonical_windows_io_path(source).parent.mkdir(parents=True, exist_ok=True)
    canonical_windows_io_path(source).write_bytes(gzip.compress(b'{"px":123}\n', mtime=0))
    _bind_catalog(root, source, dataset_id)
    assert len(str(source)) > 260

    normalized = []
    original = unpack_module._windows_io_path

    def recording_normalizer(path):
        normalized.append(str(path))
        return original(path)

    monkeypatch.setattr(unpack_module, "_windows_io_path", recording_normalizer)
    report = _expand(root)

    target = root / "usable" / "unpacked" / release_tag / f"{dataset_id}.jsonl"
    assert report["status"] == "SAFE_UNPACK_COMPLETE"
    assert canonical_windows_io_path(target).read_bytes() == b'{"px":123}\n'
    assert any(Path(path).resolve() == root.resolve() for path in normalized)
