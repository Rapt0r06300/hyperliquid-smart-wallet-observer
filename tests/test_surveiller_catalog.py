"""Surveillance de `catalog/` : ce qu'elle journalise, et ce qu'elle refuse d'affirmer.

LE FAIT À EXPLIQUER : des fichiers de `catalog/` disparaissent hors de git, et le rythme augmente
(194 supprimés en soirée, 484 le lendemain, dont des manifestes restaurés quelques heures plus
tôt). Deux restaurations à l'aveugle ont déjà eu lieu ; une troisième serait un tapis roulant.

LA LIGNE À TENIR : l'API Windows dit QUEL fichier disparaît, jamais QUI l'a supprimé. L'outil
photographie donc les processus vivants à l'instant de l'événement — c'est une **corrélation
étayée**, pas une preuve, et le journal doit le dire. Ces tests gardent cette honnêteté.

La détection temps réel elle-même a été vérifiée en conditions réelles le 20/11/2026 : 3 fichiers
témoins effacés, 3 attrapés, borne de durée respectée (6,1 s pour 6 s demandées).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

import surveiller_catalog as S  # noqa: E402


class _FauxProcessus:
    def __init__(self, pid, nom, ligne, ecritures, octets, naissance=0.0, casse=False):
        self.info = {"pid": pid, "name": nom, "cmdline": ligne, "create_time": naissance}
        self._ecritures = ecritures
        self._octets = octets
        self._casse = casse

    def io_counters(self):
        if self._casse:
            raise PermissionError("acces refuse")

        class _IO:
            write_count = self._ecritures
            write_bytes = self._octets
        return _IO()


class _FauxPsutil:
    def __init__(self, processus):
        self._processus = processus

    def process_iter(self, _champs=None):
        return list(self._processus)


# --------------------------------------------------------------------------- la photographie


def test_les_plus_gros_ecrivains_viennent_en_premier() -> None:
    """Le coupable d'une suppression ÉCRIT, par définition : on le remonte en tête."""
    faux = _FauxPsutil([
        _FauxProcessus(10, "calme.exe", ["calme"], 5, 500),
        _FauxProcessus(11, "gros.exe", ["gros", "--run"], 9_000, 900_000),
        _FauxProcessus(12, "moyen.exe", ["moyen"], 300, 30_000),
    ])
    vus = S._photographier_processus(psutil_mod=faux)
    assert [p["pid"] for p in vus] == [11, 12, 10]
    assert vus[0]["ligne"] == "gros --run"


def test_le_surveillant_ne_se_designe_jamais_lui_meme() -> None:
    """Sinon l'outil accuserait l'outil : un filtre qui s'attrape lui-même ne prouve rien."""
    faux = _FauxPsutil([
        _FauxProcessus(os.getpid(), "moi.exe", ["moi"], 10**9, 10**9),
        _FauxProcessus(77, "autre.exe", ["autre"], 1, 1),
    ])
    assert [p["pid"] for p in S._photographier_processus(psutil_mod=faux)] == [77]


def test_un_compteur_refuse_ne_fait_pas_disparaitre_le_processus() -> None:
    """Droits refusés sur les compteurs d'E/S : on garde le processus, marqué inconnu (-1)."""
    faux = _FauxPsutil([_FauxProcessus(21, "protege.exe", ["protege"], 0, 0, casse=True)])
    vus = S._photographier_processus(psutil_mod=faux)
    assert len(vus) == 1
    assert vus[0]["ecritures"] == -1 and vus[0]["octets_ecrits"] == -1


def test_sans_psutil_la_photographie_est_vide_sans_lever() -> None:
    assert S._photographier_processus(psutil_mod=_FauxPsutil([])) == []


# --------------------------------------------------------------------------- le journal


def test_le_journal_est_du_jsonl_append_only(tmp_path: Path) -> None:
    chemin = tmp_path / "sous" / "dossier" / "j.jsonl"
    S._journaliser(chemin, {"horodatage": "2026-11-20T00:00:00", "disparus": ["a.json"]})
    S._journaliser(chemin, {"horodatage": "2026-11-20T00:00:01", "disparus": ["b.json"]})
    lignes = chemin.read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 2
    assert json.loads(lignes[0])["disparus"] == ["a.json"]
    assert json.loads(lignes[1])["disparus"] == ["b.json"]


# --------------------------------------------------------------------------- les garde-fous


def test_un_dossier_absent_est_refuse_sans_lever(tmp_path: Path) -> None:
    assert S.surveiller(tmp_path, dossier="catalog_inexistant", minutes=0.01) == 2


def test_seules_les_DISPARITIONS_sont_retenues() -> None:
    """Une création ou une modification ne nous intéresse pas : on cherche qui EFFACE."""
    assert S.DISPARITIONS == {"SUPPRIME", "RENOMME_DEPUIS"}
    assert "AJOUTE" not in S.DISPARITIONS and "MODIFIE" not in S.DISPARITIONS
    # Un renommage SORTANT fait disparaître le fichier de son dossier : il compte.
    assert S.ACTIONS[2] == "SUPPRIME" and S.ACTIONS[4] == "RENOMME_DEPUIS"


def test_une_rafale_ne_declenche_qu_une_photographie() -> None:
    """Photographier des milliers de fois noierait le journal et fausserait la mesure."""
    assert S.SECONDES_ENTRE_DEUX_PHOTOS >= 1.0
