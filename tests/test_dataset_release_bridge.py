from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from hl_observer.datasets.github_release_bridge import (
    DatasetBridgeError,
    DatasetRecord,
    ReleaseAsset,
    assets_for_records,
    materialize_records,
    release_assets,
    select_records,
    verify_asset,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_release_assets_lit_les_sha256_github() -> None:
    release = {
        "assets": [
            {
                "id": 12,
                "name": "cold.zip",
                "size": 123,
                "digest": "sha256:" + "a" * 64,
            }
        ]
    }
    assets = release_assets(release)
    assert assets["cold.zip"].asset_id == 12
    assert assets["cold.zip"].sha256 == "a" * 64


def test_select_records_filtre_sans_tout_charger() -> None:
    records = [
        DatasetRecord("runtime/data/copy_vault_l2_tape.jsonl", 10, "", "zip_entry", "a.zip"),
        DatasetRecord("runtime/data/carnet_venues.jsonl", 20, "", "zip_entry", "b.zip"),
        DatasetRecord("logs/autre.log", 30, "", "zip_entry", "c.zip"),
    ]
    selected = select_records(records, contains=["copy_vault"], suffixes=[".jsonl"])
    assert [row.relative_path for row in selected] == [
        "runtime/data/copy_vault_l2_tape.jsonl"
    ]
    assert assets_for_records(selected) == ("a.zip",)


def test_verify_asset_refuse_un_mauvais_hash(tmp_path: Path) -> None:
    path = tmp_path / "asset.bin"
    path.write_bytes(b"abc")
    asset = ReleaseAsset(1, "asset.bin", 3, "sha256:" + "0" * 64)
    with pytest.raises(DatasetBridgeError, match="SHA-256 incorrect"):
        verify_asset(path, asset)


def test_materialize_records_extrait_seulement_le_fichier_demande(tmp_path: Path) -> None:
    wanted = b"donnees copy vault"
    other = b"ne doit pas etre extrait"
    archive_path = tmp_path / "cold.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("runtime/data/copy_vault.jsonl", wanted)
        archive.writestr("runtime/data/autre.jsonl", other)

    record = DatasetRecord(
        relative_path="runtime/data/copy_vault.jsonl",
        size=len(wanted),
        sha256=_sha256(wanted),
        storage="zip_entry",
        asset="cold.zip",
    )
    output = tmp_path / "out"
    created = materialize_records([record], {"cold.zip": archive_path}, output)
    assert len(created) == 1
    assert (output / "runtime/data/copy_vault.jsonl").read_bytes() == wanted
    assert not (output / "runtime/data/autre.jsonl").exists()


def test_materialize_records_recolle_un_gros_fichier(tmp_path: Path) -> None:
    part1 = b"abc"
    part2 = b"defgh"
    whole = part1 + part2
    p1 = tmp_path / "p1.bin"
    p2 = tmp_path / "p2.bin"
    p1.write_bytes(part1)
    p2.write_bytes(part2)
    record = DatasetRecord(
        relative_path="runtime/research_lab/gros.sqlite3",
        size=len(whole),
        sha256=_sha256(whole),
        storage="raw_chunks",
        chunks=(
            {"asset": "p1.bin", "part": 1},
            {"asset": "p2.bin", "part": 2},
        ),
    )
    output = tmp_path / "out"
    materialize_records(
        [record],
        {"p1.bin": p1, "p2.bin": p2},
        output,
    )
    assert (output / "runtime/research_lab/gros.sqlite3").read_bytes() == whole


def test_materialize_records_refuse_sortie_hors_dossier(tmp_path: Path) -> None:
    payload = b"x"
    archive_path = tmp_path / "cold.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../danger.txt", payload)
    record = DatasetRecord(
        relative_path="../danger.txt",
        size=1,
        sha256=_sha256(payload),
        storage="zip_entry",
        asset="cold.zip",
    )
    with pytest.raises(DatasetBridgeError, match="Chemin dangereux"):
        materialize_records([record], {"cold.zip": archive_path}, tmp_path / "out")
