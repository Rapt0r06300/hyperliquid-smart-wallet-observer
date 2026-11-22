"""Revalidation honnête des reçus : rejouer les tests AVANT de rafraîchir, ajouter sans jamais réécrire."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

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
    # 22/11/2026 : l'intention de ce test est « JAMAIS une preuve », et elle est intacte. Son
    # etiquette, elle, a change : un rejeu qui PASSE avec un fichier absent n'est plus declare
    # « rejeu rate ». L'assertion qui compte vraiment est la premiere.
    assert derniers["T-1"]["verdict"] != "VERIFIED_DONE"
    assert derniers["T-1"]["verdict"] == R.VERDICT_PREUVE_ABSENTE
    assert "src/code.py" in derniers["T-1"]["revalidation_note"]


# ───────── 18/11/2026 : UN REJEU IMPOSSIBLE N'EST PAS UN REJEU RATÉ ─────────
#
# L'outil écrivait `REVALIDATION_FAILED` pour tout code de sortie non nul. Sur machine saturée,
# Windows ne crée pas le processus : `0xC0000142`, sortie vide, aucun test exécuté (mesuré le
# 17/11 : douze groupes morts en 5 s). Lancé dans cet état, l'outil aurait déclaré fausses
# 103 preuves qu'il n'avait pas rejouées — dans un registre qu'on n'écrit qu'en ajout.


def _registre_sans_ajout(tmp_path: Path, code):
    registre = _depot(tmp_path)
    avant = registre.read_text(encoding="utf-8")
    bilan = R.revalider(tmp_path, rejouer=lambda *a: code, now_utc=NOW)
    return registre, avant, bilan


def test_un_processus_qui_ne_DEMARRE_pas_n_ecrit_RIEN(tmp_path):
    registre, avant, bilan = _registre_sans_ajout(tmp_path, 3221225794)
    assert bilan["non_mesurables"] == 3 and bilan["echecs"] == 0 and bilan["rafraichis"] == 0
    assert registre.read_text(encoding="utf-8") == avant, "aucune ligne ajoutée : rien n'a été mesuré"
    derniers = load_receipts(registre)
    for task in ("T-1", "T-2", "T-3"):
        assert derniers[task]["verdict"] == "VERIFIED_DONE", "le reçu n'est pas déclaré faux"
        assert not receipt_is_verified(derniers[task], None, tmp_path), "il reste périmé, donc visible"
        assert "revalidated_at_utc" not in derniers[task]
    assert bilan["encore_perimes"] == 4, "les 4 reçus périmés le restent : rig_020 reste rouge"


def test_une_exception_de_lancement_n_ecrit_RIEN_non_plus(tmp_path):
    registre, avant, bilan = _registre_sans_ajout(tmp_path, None)
    assert bilan["non_mesurables"] == 3 and bilan["echecs"] == 0
    assert registre.read_text(encoding="utf-8") == avant


@pytest.mark.parametrize("code", sorted(R.CODES_NON_LANCE))
def test_tous_les_codes_de_NON_LANCEMENT_sont_traites_pareil(tmp_path, code):
    registre, avant, bilan = _registre_sans_ajout(tmp_path, code)
    assert bilan["non_mesurables"] == 3 and registre.read_text(encoding="utf-8") == avant


def test_un_vrai_echec_de_tests_reste_un_VERDICT_NEGATIF(tmp_path):
    """La correction ne doit pas rendre l'outil complaisant : des tests qui tournent et échouent comptent."""
    registre, avant, bilan = _registre_sans_ajout(tmp_path, 1)
    assert bilan["echecs"] == 3 and bilan["non_mesurables"] == 0
    assert registre.read_text(encoding="utf-8") != avant
    derniers = load_receipts(registre)
    assert derniers["T-1"]["verdict"] == "REVALIDATION_FAILED"
    assert derniers["T-1"]["revalidation_note"] == "tests re-run failed"
    assert derniers["T-1"]["exit_code"] == 1


def test_un_code_de_sortie_NEGATIF_autre_qu_un_OOM_reste_un_echec(tmp_path):
    """-9 est l'OOM killer ; -11 (segfault de pytest) est un vrai échec, il doit s'écrire."""
    assert -11 not in R.CODES_NON_LANCE
    _registre, avant, bilan = _registre_sans_ajout(tmp_path, -11)
    assert bilan["echecs"] == 3 and bilan["non_mesurables"] == 0


def test_une_sortie_VIDE_vaut_non_lance(tmp_path, monkeypatch):
    """pytest écrit toujours quelque chose : sans un octet de sortie, il n'a pas tourné."""
    import subprocess as sp

    appels = []

    def faux_run(cmd, **kw):
        appels.append(cmd)
        return sp.CompletedProcess(cmd, 0, stdout="", stderr="   \n")

    monkeypatch.setattr(R, "run_isole", faux_run)
    assert R._rejouer(("tests/test_a.py",), tmp_path, 60) is None
    assert appels and "pytest" in " ".join(appels[0])


def test_une_sortie_NON_vide_rend_le_vrai_code(tmp_path, monkeypatch):
    import subprocess as sp

    monkeypatch.setattr(R, "run_isole",
                        lambda cmd, **kw: sp.CompletedProcess(cmd, 1, stdout="1 failed in 0.1s\n", stderr=""))
    assert R._rejouer(("tests/test_a.py",), tmp_path, 60) == 1
    monkeypatch.setattr(R, "run_isole",
                        lambda cmd, **kw: sp.CompletedProcess(cmd, 0, stdout="3 passed in 0.2s\n", stderr=""))
    assert R._rejouer(("tests/test_a.py",), tmp_path, 60) == 0


def test_le_code_de_non_lancement_rend_None_meme_avec_une_sortie(tmp_path, monkeypatch):
    import subprocess as sp

    monkeypatch.setattr(R, "run_isole",
                        lambda cmd, **kw: sp.CompletedProcess(cmd, 3221225794, stdout="bruit\n", stderr=""))
    assert R._rejouer(("tests/test_a.py",), tmp_path, 60) is None


def test_on_laisse_la_memoire_respirer_avant_chaque_groupe(tmp_path, monkeypatch):
    """Sans cela, le groupe suivant part dans une machine saturée et ne démarre pas du tout."""
    import subprocess as sp

    from hl_observer.ops import budget_ram as BR

    attentes = []
    monkeypatch.setattr(BR, "decision", lambda **kw: {"action": BR.PAUSER, "raison": "test"})
    monkeypatch.setattr(BR, "attendre_que_ca_respire",
                        lambda **kw: attentes.append(kw.get("limite_s")) or {"attendu_s": 1.0})
    monkeypatch.setattr(R, "run_isole",
                        lambda cmd, **kw: sp.CompletedProcess(cmd, 0, stdout="ok\n", stderr=""))
    R._rejouer(("tests/test_a.py",), tmp_path, 60)
    assert attentes == [R.ATTENTE_MEMOIRE_S]


def test_un_gouverneur_memoire_en_panne_ne_bloque_pas_la_revalidation(tmp_path, monkeypatch):
    from hl_observer.ops import budget_ram as BR

    def casse(**_kw):
        raise RuntimeError("psutil a disparu")

    monkeypatch.setattr(BR, "decision", casse)
    assert R._souffler() is None


# ───────── 18/11/2026 : LA CIRCULARITÉ D'UN REÇU QUI SE PROUVE LUI-MÊME ─────────
#
# `rig_020` LIT le registre. Tant que le reçu de la tâche qui le prouve est périmé, ce test échoue,
# donc le reçu ne peut pas être rafraîchi, donc le test continue d'échouer. Trois reçus étaient
# bloqués ainsi : ASF-RIG-010 et ASF-RIG-019 depuis le 12 et le 14/11, ASF-RIG-002 le 18/11.
# On ne les déclare pas vrais : on rejoue une SECONDE fois, registre à jour, et on n'accepte que
# si le test passe pour de bon.


def _rejoueur(resultats: dict[tuple[str, ...], list[int]]):
    """Rend des codes successifs par groupe ; garde la trace des appels."""
    appels: list[tuple[str, ...]] = []

    def rejouer(tests, root, timeout_s):
        appels.append(tests)
        suite = resultats.get(tests)
        if not suite:
            return 0
        return suite.pop(0) if len(suite) > 1 else suite[0]

    return rejouer, appels


RIG = ("tests/test_asf_rig_001_020_copy_vault.py",)


def test_un_recu_AUTO_REFERENT_obtient_une_seconde_chance_et_redevient_une_preuve(tmp_path):
    """T-3 est prouvé par le test qui lit le registre : il échoue d'abord, puis passe."""
    registre = _depot(tmp_path)
    rejouer, appels = _rejoueur({RIG: [1, 0]})          # échoue, puis passe une fois le registre à jour
    bilan = R.revalider(tmp_path, rejouer=rejouer, now_utc=NOW)
    assert appels.count(RIG) == 2, "le groupe auto-référent est rejoué une seconde fois"
    assert bilan["rafraichis_au_second_essai"] == 1 and bilan["echecs"] == 0
    derniers = load_receipts(registre)
    assert receipt_is_verified(derniers["T-3"], None, tmp_path)
    assert derniers["T-3"]["verdict"] == "VERIFIED_DONE" and derniers["T-3"]["run_status"] == "COMPLETED"


def test_un_echec_pour_une_AUTRE_cause_echoue_deux_fois_et_reste_negatif(tmp_path):
    registre = _depot(tmp_path)
    rejouer, appels = _rejoueur({RIG: [1, 1]})
    bilan = R.revalider(tmp_path, rejouer=rejouer, now_utc=NOW)
    assert appels.count(RIG) == 2 and bilan["rafraichis_au_second_essai"] == 0
    assert bilan["echecs"] == 1
    assert not receipt_is_verified(load_receipts(registre)["T-3"], None, tmp_path)


def test_un_groupe_ORDINAIRE_qui_echoue_n_a_PAS_de_seconde_chance(tmp_path):
    """Seule la circularité justifie un second essai ; sinon ce serait de la complaisance."""
    registre = _depot(tmp_path)
    rejouer, appels = _rejoueur({("tests/test_b.py",): [1, 0]})
    bilan = R.revalider(tmp_path, rejouer=rejouer, now_utc=NOW)
    assert appels.count(("tests/test_b.py",)) == 1
    assert bilan["echecs"] == 1 and bilan["rafraichis_au_second_essai"] == 0
    assert load_receipts(registre)["T-2"]["verdict"] == "REVALIDATION_FAILED"


def test_un_non_lancement_ne_declenche_pas_de_seconde_chance(tmp_path):
    """Rien n'a été écrit, donc rien n'a changé : rejouer tout de suite ne servirait à rien."""
    _depot(tmp_path)
    rejouer, appels = _rejoueur({RIG: [3221225794, 0]})
    bilan = R.revalider(tmp_path, rejouer=rejouer, now_utc=NOW)
    assert appels.count(RIG) == 1 and bilan["non_mesurables"] >= 1


def test_lit_le_registre_reconnait_les_deux_tests_concernes():
    assert R.lit_le_registre(("tests/test_asf_rig_001_020_copy_vault.py",))
    assert R.lit_le_registre(("tests/test_roadmap_3120_progress.py", "tests/test_a.py"))
    assert not R.lit_le_registre(("tests/test_a.py", "tests/test_b.py"))


# ───────── reprise des reçus déjà en échec ─────────

def test_un_recu_EN_ECHEC_n_est_repris_que_si_on_le_demande(tmp_path):
    registre = _depot(tmp_path)
    R.revalider(tmp_path, rejouer=lambda *a: 1, now_utc=NOW)          # tout échoue
    en_echec = {str(r["task_id"]) for r in R.recus_a_reprendre(registre, tmp_path)}
    assert en_echec == {"T-1", "T-2", "T-3"}
    # sans --reprendre : ces reçus ne sont plus candidats, rien ne bouge
    avant = registre.read_text(encoding="utf-8")
    bilan = R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW)
    assert bilan["perimes"] == 1 and bilan.get("repris") == 0          # seul T-4, non rejouable
    assert registre.read_text(encoding="utf-8") == avant


def test_un_recu_EN_ECHEC_repris_redevient_une_preuve_SI_les_tests_passent(tmp_path):
    registre = _depot(tmp_path)
    R.revalider(tmp_path, rejouer=lambda *a: 1, now_utc=NOW)
    bilan = R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW, reprendre=True)
    assert bilan["repris"] == 3 and bilan["rafraichis"] == 3
    derniers = load_receipts(registre)
    for task in ("T-1", "T-2", "T-3"):
        assert receipt_is_verified(derniers[task], None, tmp_path), task
    assert bilan["encore_en_echec"] == 0


def test_un_recu_EN_ECHEC_repris_qui_echoue_ENCORE_reste_en_echec(tmp_path):
    registre = _depot(tmp_path)
    R.revalider(tmp_path, rejouer=lambda *a: 1, now_utc=NOW)
    bilan = R.revalider(tmp_path, rejouer=lambda *a: 1, now_utc=NOW, reprendre=True)
    assert bilan["rafraichis"] == 0 and bilan["encore_en_echec"] == 3
    assert load_receipts(registre)["T-1"]["verdict"] == "REVALIDATION_FAILED"


def test_la_reprise_ne_fabrique_jamais_une_preuve_sans_fichier(tmp_path):
    registre = _depot(tmp_path)
    R.revalider(tmp_path, rejouer=lambda *a: 1, now_utc=NOW)
    (tmp_path / "src" / "code.py").unlink()
    R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW, reprendre=True)
    derniers = load_receipts(registre)
    # Ce qui ne doit JAMAIS arriver : une preuve fabriquee sans son fichier.
    assert derniers["T-1"]["verdict"] != "VERIFIED_DONE"
    assert derniers["T-1"]["verdict"] == R.VERDICT_PREUVE_ABSENTE


# ───────── 22/11/2026 : « PREUVE ABSENTE » N'EST PAS « PREUVE FAUSSE » ─────────
#
# Les neuf reçus ASF-113..120 et ASF-RIG-019 étaient rouges depuis le 18/11 avec `exit_code: 0`.
# Mesure du 22/11 : leurs tests passent (32 verts en 3,6 s) et `_rejouer` rend bien 0. Un SEUL
# fichier épinglé manque, le même pour les neuf : `POUSSER-GITHUB-FORCE.cmd`, supprimé par le
# commit b44aac91 du 18/11 intitulé « lanceur: POUSSER-GITHUB, sans le FORCE qu'il ne fait pas ».
# Sa suppression était donc une correction de véracité : le recréer serait une régression.
#
# L'outil écrivait pourtant `REVALIDATION_FAILED` — « on a rejoué, c'est faux » — pour un rejeu
# RÉUSSI dont seule une empreinte est incalculable. C'est la confusion que ce dépôt combat
# partout ailleurs : une ABSENCE n'est pas une NÉGATION. On distingue donc les deux états, sans
# qu'aucun des deux ne compte comme une preuve.


def test_un_rejeu_REUSSI_avec_un_fichier_absent_n_est_PAS_un_echec_de_rejeu(tmp_path):
    registre = _depot(tmp_path)
    (tmp_path / "src" / "code.py").unlink()
    R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW)
    derniers = load_receipts(registre)
    assert derniers["T-1"]["verdict"] == R.VERDICT_PREUVE_ABSENTE
    assert derniers["T-1"]["verdict"] != "REVALIDATION_FAILED"
    # Le rejeu a eu lieu et il a réussi : mentir sur ce point rendrait l'état illisible.
    assert derniers["T-1"]["exit_code"] == 0


def test_la_preuve_absente_NOMME_le_fichier_pour_qu_on_puisse_agir(tmp_path):
    registre = _depot(tmp_path)
    (tmp_path / "src" / "code.py").unlink()
    R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW)
    recu = load_receipts(registre)["T-1"]
    assert recu["fichiers_de_preuve_absents"] == ["src/code.py"]
    assert "src/code.py" in recu["revalidation_note"]


def test_une_preuve_absente_ne_compte_JAMAIS_comme_une_preuve(tmp_path):
    registre = _depot(tmp_path)
    (tmp_path / "src" / "code.py").unlink()
    R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW)
    recu = load_receipts(registre)["T-1"]
    # La garde qui compte : le décompte de la feuille de route ne doit pas bouger d'un pouce.
    assert recu["verdict"] != "VERIFIED_DONE"
    assert not receipt_is_verified(recu, recu.get("sha"), tmp_path)


def test_un_VRAI_echec_de_tests_reste_distinct_d_une_preuve_absente(tmp_path):
    registre = _depot(tmp_path)
    (tmp_path / "src" / "code.py").unlink()
    R.revalider(tmp_path, rejouer=lambda *a: 1, now_utc=NOW)
    recu = load_receipts(registre)["T-1"]
    # Tests rouges : le verdict négatif garde tout son sens, l'absence ne l'efface pas.
    assert recu["verdict"] == "REVALIDATION_FAILED"
    assert recu["revalidation_note"] == "tests re-run failed"


def test_le_bilan_compte_les_preuves_absentes_a_part(tmp_path):
    _depot(tmp_path)
    (tmp_path / "src" / "code.py").unlink()
    bilan = R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW)
    assert bilan["preuves_absentes"] >= 1
    assert bilan["echecs"] == 0          # aucun rejeu n'a échoué : il ne faut pas l'écrire


def test_une_preuve_absente_est_REPRISE_si_le_fichier_revient(tmp_path):
    registre = _depot(tmp_path)
    cible = tmp_path / "src" / "code.py"
    garde = cible.read_bytes()
    cible.unlink()
    R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW)
    assert load_receipts(registre)["T-1"]["verdict"] == R.VERDICT_PREUVE_ABSENTE
    # Le fichier revient : une reprise doit pouvoir rendre sa preuve au reçu.
    cible.write_bytes(garde)
    R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW, reprendre=True)
    assert load_receipts(registre)["T-1"]["verdict"] == "VERIFIED_DONE"


def _depot_minimal(tmp_path: Path) -> Path:
    """Un dépôt où SEUL le compteur `preuves_absentes` peut être non nul.

    Le `_depot` partagé contient un reçu sans test rejouable (T-4) : il reste périmé, donc
    `encore_perimes` vaut 1 et `non_resolu` est vrai QUOI QU'IL ARRIVE. Impossible d'y isoler
    la contribution de `preuves_absentes` — c'est ce qui a rendu la garde aveugle trois fois.
    """
    (tmp_path / "tests").mkdir()
    (tmp_path / "src").mkdir()
    for nom in ("tests/test_a.py", "src/code.py"):
        (tmp_path / nom).write_text(f"# {nom}" + chr(10), encoding="utf-8")
    registre = tmp_path / R.RECEIPTS
    registre.parent.mkdir(parents=True)
    registre.write_text(
        json.dumps(_recu(tmp_path, "T-1", ["src/code.py", "tests/test_a.py"],
                         "py -3 -m pytest -q tests/test_a.py")) + chr(10),
        encoding="utf-8")
    (tmp_path / "src" / "code.py").write_text("# code modifié" + chr(10), encoding="utf-8")
    return registre


def test_une_preuve_absente_ne_fait_JAMAIS_sortir_vert(tmp_path, monkeypatch):
    """La garde qui empêche la correction du 22/11 de masquer les reçus qu'elle renomme.

    ⚠️ TROIS versions aveugles avant celle-ci (22/11/2026), trois raisons différentes, et le
    même symptôme : l'injection qui retire `preuves_absentes` du code de sortie restait VERTE.

    1. `_rejouer` tournait pour de vrai : dans un dépôt bidon pytest ne collecte rien et rend 5,
       donc `echecs` était non nul et la sortie valait 3 de toute façon.
    2. `monkeypatch.setattr(R, "_rejouer", ...)` n'y change rien : `revalider` reçoit
       `rejouer=_rejouer` comme valeur par défaut d'un paramètre, liée à la définition. Il faut
       remplacer la valeur dans `__kwdefaults__`, seul endroit que `main()` lira.
    3. Le `_depot` partagé laissait `encore_perimes` à 1 (un reçu sans test rejouable), ce qui
       suffisait à faire sortir 3. D'où `_depot_minimal`.

    La leçon, chère : une garde ne vaut que si l'on a vu ROUGIR le défaut qu'elle vise.
    """
    _depot_minimal(tmp_path)
    (tmp_path / "src" / "code.py").unlink()
    monkeypatch.setitem(R.revalider.__kwdefaults__, "rejouer", lambda *a, **k: 0)
    code = R.main(["--root", str(tmp_path), "--reprendre"])
    assert code == 3


def test_le_bilan_ne_melange_pas_echec_et_preuve_absente(tmp_path):
    _depot(tmp_path)
    (tmp_path / "src" / "code.py").unlink()
    bilan = R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW)
    assert bilan["encore_en_echec"] == 0
    assert bilan["encore_preuves_absentes"] >= 1


def test_le_listage_ne_dit_PAS_en_echec_pour_une_preuve_absente(tmp_path, capsys):
    """`--lister` séparait encore les deux états, contrairement au bilan de `revalider()`.

    Afficher « en_echec: 9 » pour neuf reçus dont le rejeu PASSE était exactement le mensonge
    que la distinction du 22/11 visait à supprimer — et il a survécu une heure de plus que la
    correction, parce que j'avais changé `revalider()` sans relire la branche de listage.
    """
    _depot_minimal(tmp_path)
    (tmp_path / "src" / "code.py").unlink()
    R.revalider(tmp_path, rejouer=lambda *a: 0, now_utc=NOW)
    capsys.readouterr()
    R.main(["--root", str(tmp_path), "--lister"])
    rendu = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rendu["preuves_absentes"] >= 1
    assert rendu["en_echec"] == 0, "une preuve absente n'est pas un rejeu rate"
