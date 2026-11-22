"""Repointer une preuve est dangereux : ce sont les REFUS qui font la valeur de l'outil.

Changer ce qu'un reçu DÉSIGNE, c'est toucher à la définition de la preuve. Un outil qui
accepterait n'importe quel repointage permettrait de faire passer le décompte de 3 111 à 3 120
sans qu'aucun test ne le justifie. On teste donc d'abord tout ce qu'il doit refuser, et surtout
qu'il **ne décerne jamais la preuve lui-même**.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _chemin in (ROOT / "src", ROOT / "tools"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import repointer_preuve_deplacee as R  # noqa: E402
import revalider_receipts as RR  # noqa: E402
from alina_roadmap_progress import _file_set_fingerprint, load_receipts  # noqa: E402

NOW = "2026-11-22T12:00:00+00:00"


def _depot(tmp_path: Path, *, le_test_cite_le_successeur: bool = True,
           ancien_existe: bool = False) -> Path:
    """Un dépôt minimal : un reçu EVIDENCE_FILE_ABSENT qui épingle un fichier disparu."""
    (tmp_path / "tests").mkdir()
    corps = "# test\n"
    if le_test_cite_le_successeur:
        corps += 'CIBLE = ROOT / "NOUVEAU.cmd"\n'
    (tmp_path / "tests" / "test_x.py").write_text(corps, encoding="utf-8")
    (tmp_path / "NOUVEAU.cmd").write_text("@echo off\n", encoding="utf-8")
    if ancien_existe:
        (tmp_path / "ANCIEN.cmd").write_text("@echo off\n", encoding="utf-8")
    files = ["ANCIEN.cmd", "tests/test_x.py"]
    # Fidèle au réel : le reçu porte une empreinte pour le fichier DISPARU aussi, calculée
    # quand il existait encore. C'est précisément ce qui rend l'empreinte incalculable
    # aujourd'hui, donc l'état EVIDENCE_FILE_ABSENT.
    hashes = {
        "ANCIEN.cmd": hashlib.sha256(b"@echo off\n").hexdigest(),
        "tests/test_x.py": hashlib.sha256(corps.encode()).hexdigest(),
    }
    recu = {
        "task_id": "T-9", "verdict": "EVIDENCE_FILE_ABSENT", "run_status": "EVIDENCE_MISSING",
        "command": "py -3 -m pytest -q tests/test_x.py", "exit_code": 0,
        "evidence": ["pytest"], "files": files, "file_sha256": hashes,
        "sha": _file_set_fingerprint(files, hashes),
    }
    registre = tmp_path / RR.RECEIPTS
    registre.parent.mkdir(parents=True)
    registre.write_text(json.dumps(recu) + "\n", encoding="utf-8")
    return registre


def test_repointage_FACTUEL_est_accepte(tmp_path: Path) -> None:
    _depot(tmp_path)
    bilan = R.examiner(tmp_path, de="ANCIEN.cmd", vers="NOUVEAU.cmd")
    assert bilan["verdict"] == "REPOINTABLE"
    assert bilan["recus"] == ["T-9"]


def test_REFUS_si_l_ancien_chemin_existe_encore(tmp_path: Path) -> None:
    """On ne « déplace » pas une preuve qui est là : ce serait la remplacer."""
    _depot(tmp_path, ancien_existe=True)
    bilan = R.examiner(tmp_path, de="ANCIEN.cmd", vers="NOUVEAU.cmd")
    assert bilan["verdict"] == "REFUSE"
    assert any("existe encore" in m for m in bilan["motifs"]), bilan["motifs"]


def test_REFUS_si_le_successeur_est_absent(tmp_path: Path) -> None:
    _depot(tmp_path)
    bilan = R.examiner(tmp_path, de="ANCIEN.cmd", vers="JAMAIS_ECRIT.cmd")
    assert bilan["verdict"] == "REFUSE"
    assert any("absent" in m for m in bilan["motifs"]), bilan["motifs"]


def test_REFUS_si_aucun_test_du_recu_ne_cite_le_successeur(tmp_path: Path) -> None:
    """LA garde : la preuve suit ce que le test LIT, pas ce qui arrangerait le decompte."""
    _depot(tmp_path, le_test_cite_le_successeur=False)
    bilan = R.examiner(tmp_path, de="ANCIEN.cmd", vers="NOUVEAU.cmd")
    assert bilan["verdict"] == "RIEN_A_REPOINTER"
    assert bilan["ignores"] and "ne cite" in bilan["ignores"][0]["pourquoi"]


def test_SANS_appliquer_rien_nest_ecrit(tmp_path: Path) -> None:
    registre = _depot(tmp_path)
    avant = registre.read_text(encoding="utf-8")
    bilan = R.repointer(tmp_path, de="ANCIEN.cmd", vers="NOUVEAU.cmd", appliquer=False)
    assert bilan["ecrit"] == 0
    assert registre.read_text(encoding="utf-8") == avant


def test_le_repointage_NE_DECERNE_JAMAIS_la_preuve(tmp_path: Path) -> None:
    """Le cœur de la sûreté : la liste est corrigée, le verdict NE BOUGE PAS.

    Seul `revalider_receipts` peut rendre un reçu VERIFIED_DONE, et seulement en rejouant ses
    tests. Si cet outil décernait la preuve, 3 111 deviendrait 3 120 sans qu'un seul test tourne.
    """
    registre = _depot(tmp_path)
    R.repointer(tmp_path, de="ANCIEN.cmd", vers="NOUVEAU.cmd", appliquer=True)
    dernier = load_receipts(registre)["T-9"]
    assert dernier["files"] == ["NOUVEAU.cmd", "tests/test_x.py"], dernier["files"]
    assert dernier["verdict"] != "VERIFIED_DONE", "un repointage n'est pas une preuve"
    assert dernier["verdict"] == "EVIDENCE_FILE_ABSENT"
    assert dernier["repointage"]["de"] == "ANCIEN.cmd"


def test_le_registre_reste_APPEND_ONLY(tmp_path: Path) -> None:
    registre = _depot(tmp_path)
    avant = registre.read_text(encoding="utf-8")
    R.repointer(tmp_path, de="ANCIEN.cmd", vers="NOUVEAU.cmd", appliquer=True)
    apres = registre.read_text(encoding="utf-8")
    assert apres.startswith(avant), "aucune ligne existante ne doit etre modifiee"
    assert len(apres.splitlines()) == len(avant.splitlines()) + 1


def test_une_sauvegarde_est_prise_avant_d_ecrire(tmp_path: Path) -> None:
    _depot(tmp_path)
    bilan = R.repointer(tmp_path, de="ANCIEN.cmd", vers="NOUVEAU.cmd", appliquer=True)
    assert bilan.get("sauvegarde"), bilan
    assert (tmp_path / bilan["sauvegarde"]).is_file()
