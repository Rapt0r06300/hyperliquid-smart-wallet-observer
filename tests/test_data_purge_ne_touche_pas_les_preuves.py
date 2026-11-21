"""La purge ne peut PAS entrer dans une preuve, et ses refus sont visibles.

POURQUOI CE FICHIER EXISTE. La mesure du 21/11/2026 a montre que `ops/data_purge.py` n'etait
atteint par AUCUN test, meme indirectement, et n'etait appele par aucun code -- seul un
commentaire de `LANCER_HYPERSMART.cmd` le mentionne (« ENG-053 »). Lance a blanc sur le depot,
il annoncait 18 fichiers / 16,3 Mo a supprimer, dont **12 journaux de session archives** sous
`logs/.../_archives/`. Un dossier `_archives` existe pour CONSERVER : une purge qui y entre
detruit la preuve qu'on garde pour la relire, ce que la regle premiere du depot interdit.

Une fonction dormante n'est pas une fonction inoffensive : il suffit qu'on la cable.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from hl_observer.ops.data_purge import (
    DEFAULT_MAX_AGE_DAYS,
    PROTECTED_PATH_PARTS,
    chemin_protege,
    purge_stale_files,
)

VIEUX = time.time() - (DEFAULT_MAX_AGE_DAYS + 5) * 86400


def _vieux_fichier(chemin: Path, octets: bytes = b"x" * 1024) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(octets)
    import os

    os.utime(chemin, (VIEUX, VIEUX))
    return chemin


# ------------------------------------------------------------------ la garde elle-meme
@pytest.mark.parametrize("partie", PROTECTED_PATH_PARTS)
def test_chaque_dossier_protege_est_reconnu(partie):
    assert chemin_protege(Path("logs") / partie / "x.log") == partie


def test_la_garde_compare_des_COMPOSANTS_pas_des_sous_chaines():
    """`mes_backupsfoo.log` n'est pas une sauvegarde : une garde trop large protegerait du bruit."""
    assert chemin_protege(Path("logs/mes_backupsfoo.log")) is None
    assert chemin_protege(Path("logs/backups/x.log")) == "backups"


# ------------------------------------------------------------------ le comportement reel
def test_un_journal_archive_est_REFUSE_et_le_refus_est_RENDU(tmp_path):
    """LE CAS MESURE : 12 journaux de session archives etaient sur la liste de suppression."""
    archive = _vieux_fichier(
        tmp_path / "logs" / "_archives" / "session_20261027_051645" / "observer.log")
    rapport = purge_stale_files(tmp_path, dry_run=False)
    assert archive.exists(), "un journal archive a ete supprime"
    assert rapport["removed_count"] == 0
    assert rapport["protected_count"] == 1
    assert "_archives" in rapport["protected_files"][0]


def test_le_coffre_certifie_et_les_recus_sont_intouchables(tmp_path):
    cibles = [
        _vieux_fichier(tmp_path / "runtime" / "data" / "coffre_certifie" / "a.log"),
        _vieux_fichier(tmp_path / "runtime" / "data" / "receipts" / "b.zip"),
        _vieux_fichier(tmp_path / "runtime" / "data" / "market_ticks" / "c.tmp"),
        _vieux_fichier(tmp_path / "runtime" / "data" / "backups" / "d.log"),
    ]
    rapport = purge_stale_files(tmp_path, dry_run=False)
    assert all(c.exists() for c in cibles)
    assert rapport["removed_count"] == 0 and rapport["protected_count"] == 4


def test_un_vrai_dechet_est_bien_supprime(tmp_path):
    """LA MOITIE QUI COMPTE : une garde qui empeche tout ne protege plus rien, elle casse."""
    dechet = _vieux_fichier(tmp_path / "logs" / "vieux.log")
    rapport = purge_stale_files(tmp_path, dry_run=False)
    assert not dechet.exists()
    assert rapport["removed_count"] == 1 and rapport["protected_count"] == 0


def test_un_fichier_RECENT_est_laisse_tranquille(tmp_path):
    recent = tmp_path / "logs" / "aujourdhui.log"
    recent.parent.mkdir(parents=True)
    recent.write_bytes(b"x")
    rapport = purge_stale_files(tmp_path, dry_run=False)
    assert recent.exists() and rapport["removed_count"] == 0


def test_une_extension_hors_liste_est_laissee_tranquille(tmp_path):
    """Un `.jsonl.gz` collecte n'est pas un dechet : il ne doit jamais entrer dans la purge."""
    tape = _vieux_fichier(tmp_path / "runtime" / "data" / "shards" / "ticks.jsonl.gz")
    rapport = purge_stale_files(tmp_path, dry_run=False)
    assert tape.exists() and rapport["removed_count"] == 0


def test_le_mode_a_blanc_ne_supprime_rien_mais_annonce_tout(tmp_path):
    """`dry_run` doit pouvoir etre lu comme une PREVISION fidele, sinon il ne sert a rien."""
    dechet = _vieux_fichier(tmp_path / "logs" / "vieux.log")
    rapport = purge_stale_files(tmp_path, dry_run=True)
    assert dechet.exists()
    assert rapport["removed_count"] == 1 and rapport["dry_run"] is True
    assert rapport["files"] == ["logs/vieux.log".replace("/", __import__("os").sep)]


def test_un_dossier_absent_ne_fait_pas_lever(tmp_path):
    rapport = purge_stale_files(tmp_path)
    assert rapport["removed_count"] == 0 and rapport["protected_count"] == 0
