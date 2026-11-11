"""Revalidation honnête des reçus : rejouer les tests AVANT de rafraîchir, ajouter sans jamais réécrire."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import revalider_receipts as R  # noqa: E402
from alina_roadmap_progress import _file_set_fingerprint, load_receipts, receipt_is_verified  # noqa: E402

NOW = "2026-11-11T15:00:00+00:00"


def _recu(root: Path, task_id: str, files: list[str], command: str) -> dict:
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
    return {"task_id": task_id, "verdict": "VERIFIED_DONE", "run_status": "COMPLETED", "command": command,
            "exit_code": 0, "evidence": ["pytest"], "files": files, "file_sha256": hashes,
            "sha": _file_set_fingerprint(files, hashes)}


def _depot(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "src").mkdir()
    for nom in ("tests/test_a.py", "tests/test_b.py", "tests/test_asf_rig_001_020_copy_vault.py", "src/code.py"):
        (tmp_path / nom).write_text(f"# {nom}\n", encoding="utf-8")
    recus = [
        _recu(tmp_path, "T-1", ["src/code.py", "tests/test_a.py"], "py -3 -m pytest -q tests/test_a.py"),
        _recu(tmp_path, "T-2", ["src/code.py", "tests/test_b.py"], "py -3 -m pytest -q tests/test_b.py"),
        _recu(tmp_path, "T-3", ["src/code.py"], "py -3 -m pytest -q tests/test_asf_rig_001_020_copy_vault.py"),
        _recu(tmp_path, "T-4", ["src/code.py"], "controle manuel sans test rejouable"),
        _recu(tmp_path, "T-5", ["tests/test_b.py"], "py -3 -m pytest -q tests/test_b.py"),      # restera valide
    ]
    registre = tmp_path / R.RECEIPTS
    registre.parent.mkdir(parents=True)
    registre.write_text("".join(json.dumps(r) + "\n" for r in recus), encoding="utf-8")
    (tmp_path / "src" / "code.py").write_text("# code modifié\n", encoding="utf-8")      # périme T-1 à T-4
    return registre


def test_un_recu_perime_n_est_rafraichi_qu_apres_avoir_rejoue_ses_tests(tmp_path):
    registre = _depot(tmp_path)
    avant = registre.read_text(encoding="utf-8")
    assert {r["task_id"] for r in R.recus_perimes(registre, tmp_path)} == {"T-1", "T-2", "T-3", "T-4"}
    ordre: list[tuple[str, ...]] = []

    def rejouer(tests, root, timeout_s):
        ordre.append(tests)
        return 1 if tests == ("tests/test_b.py",) else 0          # le test de T-2 échoue

    bilan = R.revalider(tmp_path, rejouer=rejouer, now_utc=NOW)

    assert bilan["perimes"] == 4 and bilan["rafraichis"] == 2 and bilan["echecs"] == 1
    assert bilan["non_rejouables"] == 1 and bilan["groupes_de_tests"] == 3
    # le test qui lit le registre est rejoué en dernier
    assert ordre[-1] == ("tests/test_asf_rig_001_020_copy_vault.py",)
    # ajout seul : les lignes d'origine sont intactes, la sauvegarde est identique à l'état de départ
    apres = registre.read_text(encoding="utf-8")
    assert apres.startswith(avant) and len(apres.splitlines()) == len(avant.splitlines()) + 3
    assert (tmp_path / bilan["sauvegarde"]).read_text(encoding="utf-8") == avant

    derniers = load_receipts(registre)
    assert receipt_is_verified(derniers["T-1"], None, tmp_path) and derniers["T-1"]["revalidated_at_utc"] == NOW
    assert receipt_is_verified(derniers["T-3"], None, tmp_path)
    # test rouge : la tâche n'est plus comptée comme faite, et c'est écrit
    assert derniers["T-2"]["verdict"] == "REVALIDATION_FAILED" and derniers["T-2"]["exit_code"] == 1
    assert not receipt_is_verified(derniers["T-2"], None, tmp_path)
    # aucune preuve rejouable : le reçu reste périmé et visible, jamais rafraîchi à l'aveugle
    assert not receipt_is_verified(derniers["T-4"], None, tmp_path) and "revalidated_at_utc" not in derniers["T-4"]
    assert bilan["encore_perimes"] == 1
    # rejouer l'outil ne duplique rien : seul le reçu non rejouable reste à traiter
    assert R.revalider(tmp_path, rejouer=rejouer, now_utc=NOW)["rafraichis"] == 0
    assert len(registre.read_text(encoding="utf-8").splitlines()) == len(apres.splitlines())


def test_rien_a_faire_ne_touche_pas_au_registre(tmp_path):
    registre = _depot(tmp_path)
    (tmp_path / "src" / "code.py").write_text("# src/code.py\n", encoding="utf-8")       # contenu d'origine
    avant = registre.read_text(encoding="utf-8")
    bilan = R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW)
    assert bilan["perimes"] == 0 and bilan["sauvegarde"] is None
    assert registre.read_text(encoding="utf-8") == avant and not (tmp_path / R.BACKUPS).exists()


def test_un_fichier_de_preuve_disparu_ne_donne_jamais_un_recu_valide(tmp_path):
    registre = _depot(tmp_path)
    (tmp_path / "src" / "code.py").unlink()
    R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW)
    derniers = load_receipts(registre)
    assert derniers["T-1"]["verdict"] == "REVALIDATION_FAILED"
    assert derniers["T-1"]["revalidation_note"] == "evidence file missing"
