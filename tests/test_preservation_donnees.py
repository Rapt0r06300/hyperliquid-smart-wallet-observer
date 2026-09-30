"""PRÉSERVATION DES DONNÉES COLLECTÉES (Flo 25/07) — « au redémarrage on garde ce qu'on a collecté ;
on n'écrase pas les anciennes sessions sauf si elles sont mauvaises/fausses ».

Prouve : sceller_shard SCELLE la tape en shard immuable, borne le SET DE TRAVAIL à max_shards (fraîcheur),
mais DÉPLACE les plus vieux vers bbo_shards_archive/ au lieu de les SUPPRIMER — aucune donnée valide perdue.
"""
from __future__ import annotations

import gzip
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("collecter_bbo", _ROOT / "tools" / "collecter_bbo.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)


def _remplir_tape(root: Path, marqueur: str, octets: int) -> None:
    p = root / B.TAPE
    p.parent.mkdir(parents=True, exist_ok=True)
    ligne = ('{"venue":"HL","coin":"%s","x":"' % marqueur) + "a" * 200 + '"}\n'
    with p.open("w", encoding="utf-8") as f:
        while p.stat().st_size < octets:
            for _ in range(500):
                f.write(ligne)
            f.flush()


def test_scellage_ne_supprime_jamais_archive_a_la_place(tmp_path):
    seuil = 50_000
    # scelle 4 tapes avec un set de travail borné à 2 -> 2 restent, 2 partent en ARCHIVE (aucune perdue)
    for i in range(4):
        _remplir_tape(tmp_path, "S%d" % i, seuil + 5_000)
        nom = B.sceller_shard(tmp_path, seuil_octets=seuil, max_shards=2)
        assert nom is not None
    travail = sorted((tmp_path / B.SHARDS_DIR).glob("bbo_tape_*.jsonl.gz"))
    archive = sorted((tmp_path / B.ARCHIVE_DIR).glob("bbo_tape_*.jsonl.gz"))
    assert len(travail) == 2, "set de travail borné (fraîcheur)"
    assert len(archive) == 2, "les plus vieux sont ARCHIVÉS, pas supprimés"
    assert len(travail) + len(archive) == 4, "AUCUN shard perdu : 4 scellés = 4 conservés"


def test_shard_reste_lisible_apres_archivage(tmp_path):
    seuil = 40_000
    _remplir_tape(tmp_path, "VIEUX", seuil + 5_000)
    B.sceller_shard(tmp_path, seuil_octets=seuil, max_shards=1)
    _remplir_tape(tmp_path, "NEUF", seuil + 5_000)
    B.sceller_shard(tmp_path, seuil_octets=seuil, max_shards=1)
    archive = list((tmp_path / B.ARCHIVE_DIR).glob("bbo_tape_*.jsonl.gz"))
    assert len(archive) == 1
    contenu = gzip.open(archive[0], "rt", encoding="utf-8").read()
    assert "VIEUX" in contenu, "la donnée archivée reste intacte et relisible pour mesurer plus tard"


def test_tape_vivante_repart_vide_mais_apres_scellage(tmp_path):
    seuil = 40_000
    _remplir_tape(tmp_path, "X", seuil + 5_000)
    B.sceller_shard(tmp_path, seuil_octets=seuil, max_shards=5)
    # après scellage la tape vivante est vide (= récent), mais son contenu est SAUF dans le shard
    assert (tmp_path / B.TAPE).read_text(encoding="utf-8") == ""
    assert len(list((tmp_path / B.SHARDS_DIR).glob("bbo_tape_*.jsonl.gz"))) == 1


def test_sous_le_seuil_ne_scelle_pas_ne_perd_rien(tmp_path):
    p = tmp_path / B.TAPE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"venue":"HL","coin":"PETIT"}\n', encoding="utf-8")   # quelques octets < seuil
    assert B.sceller_shard(tmp_path, seuil_octets=80_000, max_shards=5) is None
    assert "PETIT" in p.read_text(encoding="utf-8"), "la tape vivante intacte (rien perdu)"
