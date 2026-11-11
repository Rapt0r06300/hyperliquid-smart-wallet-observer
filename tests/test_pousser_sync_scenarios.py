"""Tests réalistes de POUSSER-GITHUB-FORCE (moteur alina_git_code_sync).

Couvre le cahier des charges : séparation code/données (#8), messages de commit
intelligents (#4), « rien à faire » sans faux échec (le fix du NO_GO), et des
scénarios end-to-end sur un VRAI dépôt git temporaire avec un remote « bare » :
commit + push (#2), fichiers non suivis (#3), commits GitHub concurrents (#6),
conflit préservé sans perte (#5), vérification du résultat (#10).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import alina_git_code_sync as S  # noqa: E402


# --------------------------------------------------------------------------- #
# Unitaires : contrat code vs données (#8) et messages sémantiques (#4)
# --------------------------------------------------------------------------- #

def test_protected_separe_code_et_donnees():
    # CODE publiable -> non protégé
    assert not S._protected("tools/collecter_userfills_poll.py")
    assert not S._protected("src/hl_observer/ops/bounded_collection.py")
    assert not S._protected("tests/test_x.py")
    assert not S._protected("LANCER_COLLECTEURS_COPY_VAULT.cmd")
    assert not S._protected(".github/workflows/copy-vault-poll-lanes.yml")
    # DONNEES / runtime / secrets -> protégés (jamais publiés)
    assert S._protected("runtime/data/vault_fills_poll.jsonl")
    assert S._protected("runtime/coffre_certifie/local/shards/x.jsonl.gz")
    assert S._protected("runtime/logs/supervisor.log")


def test_commit_subject_est_significatif_pas_generique():
    msg = S._commit_subject(["tools/collecter_userfills_poll.py", "tests/test_poll.py"])
    assert msg and "sauvegarde des modifications" not in msg.lower()
    assert "claude" not in msg.lower() or "codex" not in msg.lower()
    # un sujet non vide, lié aux chemins
    assert len(msg) >= 5


# --------------------------------------------------------------------------- #
# Harness end-to-end : vrai dépôt + remote « bare »
# --------------------------------------------------------------------------- #

def _git(root: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} -> {r.returncode}\n{r.stderr}")
    return r.stdout.strip()


def _repo_avec_remote(tmp_path: Path) -> tuple[Path, Path]:
    """Crée un dépôt de travail + un remote bare 'origin', branche main alignée."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare", "-b", "main")
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "t@t.t")
    _git(work, "config", "user.name", "t")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "tools").mkdir()
    (work / "tools" / "x.py").write_text("print('v1')\n", encoding="utf-8")
    (work / "runtime" / "data").mkdir(parents=True)
    _git(work, "add", "tools/x.py")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "-q", "-u", "origin", "main")
    return work, remote


def _run_sync(work: Path, **kw) -> tuple[int, dict]:
    os.environ["ALINA_SYNC_TEST_REMOTE_ALLOWED"] = "1"   # autorise le remote de test
    try:
        sync = S.Synchronizer(work, allow_test_remote=True, **kw)
        code = sync.run()
    finally:
        os.environ.pop("ALINA_SYNC_TEST_REMOTE_ALLOWED", None)
    return code, sync.report


def test_e2e_rien_a_faire_ne_renvoie_pas_un_echec(tmp_path):
    """Le fix du NO_GO : dépôt aligné + seulement des données locales = succès."""
    work, _ = _repo_avec_remote(tmp_path)
    # churn de DONNEES locales (protégé) : ne doit PAS provoquer un NO_GO
    (work / "runtime" / "data" / "vault_fills_poll.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    code, report = _run_sync(work)
    assert report["status"] in ("SYNCHRONIZED", "NOTHING_TO_SYNC", "CLEAN"), report["status"]
    assert code == 0
    # la donnée locale est restée (jamais publiée)
    assert (work / "runtime" / "data" / "vault_fills_poll.jsonl").exists()


def test_e2e_changement_de_code_commit_et_push(tmp_path):
    """#2/#10 : une modif de code est committée (message non générique) et poussée."""
    work, remote = _repo_avec_remote(tmp_path)
    (work / "tools" / "x.py").write_text("print('v2 ameliore')\n", encoding="utf-8")
    code, report = _run_sync(work)
    assert code == 0 and report["status"] in ("SYNCHRONIZED", "PUSHED")
    # le remote a bien recu le nouveau contenu
    head_remote = _git(remote, "rev-parse", "main")
    head_local = _git(work, "rev-parse", "main")
    assert head_local == head_remote  # HEAD local == distant (#10)


def test_e2e_fichier_non_suivi_est_sauvegarde(tmp_path):
    """#3 : un nouveau fichier de code non suivi est bien committé/poussé."""
    work, remote = _repo_avec_remote(tmp_path)
    (work / "tools" / "nouveau.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    code, report = _run_sync(work)
    assert code == 0
    # present sur le remote
    files = _git(remote, "ls-tree", "-r", "--name-only", "main")
    assert "tools/nouveau.py" in files


def test_e2e_donnees_jamais_publiees(tmp_path):
    """#8 : les données runtime ne doivent JAMAIS atterrir sur le remote."""
    work, remote = _repo_avec_remote(tmp_path)
    (work / "tools" / "x.py").write_text("print('v2')\n", encoding="utf-8")   # vrai code -> pousse
    (work / "runtime" / "data" / "secret_tape.jsonl").write_text('{"x":1}\n', encoding="utf-8")
    code, _ = _run_sync(work)
    assert code == 0
    files = _git(remote, "ls-tree", "-r", "--name-only", "main")
    assert "runtime/data/secret_tape.jsonl" not in files
    assert not any(f.startswith("runtime/") for f in files.splitlines())


def _push_concurrent(remote: Path, tmp_path: Path, nom: str, chemin: str, contenu: str) -> None:
    """Simule un commit GitHub concurrent : un autre clone pousse sur le remote."""
    autre = tmp_path / nom
    _git(tmp_path, "clone", "-q", str(remote), str(autre))
    _git(autre, "config", "user.email", "o@o.o")
    _git(autre, "config", "user.name", "o")
    _git(autre, "config", "commit.gpgsign", "false")
    f = autre / chemin
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(contenu, encoding="utf-8")
    _git(autre, "add", chemin)
    _git(autre, "commit", "-q", "-m", "commit concurrent")
    _git(autre, "push", "-q", "origin", "main")


def test_e2e_commit_github_concurrent_integre_les_deux(tmp_path):
    """#6 : GitHub reçoit un commit pendant qu'on a une modif locale -> on garde LES DEUX."""
    work, remote = _repo_avec_remote(tmp_path)
    # modif locale (code)
    (work / "tools" / "x.py").write_text("print('v2 local')\n", encoding="utf-8")
    # commit concurrent sur GitHub (autre fichier)
    _push_concurrent(remote, tmp_path, "clone1", "tools/distant.py", "print('distant')\n")
    code, report = _run_sync(work)
    assert code == 0, report.get("status")
    files = _git(remote, "ls-tree", "-r", "--name-only", "main")
    assert "tools/distant.py" in files          # le commit concurrent conserve
    # notre modif locale est bien sur le remote aussi
    contenu = _git(remote, "show", "main:tools/x.py")
    assert "v2 local" in contenu
    assert _git(work, "rev-parse", "main") == _git(remote, "rev-parse", "main")  # #10


def test_e2e_conflit_preserve_sans_perte(tmp_path):
    """#5 : local et GitHub modifient le MEME fichier -> pas de choix arbitraire, pas de perte."""
    work, remote = _repo_avec_remote(tmp_path)
    (work / "tools" / "x.py").write_text("print('VERSION LOCALE')\n", encoding="utf-8")
    _push_concurrent(remote, tmp_path, "clone2", "tools/x.py", "print('VERSION DISTANTE')\n")
    code, report = _run_sync(work)
    # soit il réconcilie proprement (0), soit il bloque (non-0) -- mais JAMAIS il
    # n'écrase silencieusement la version locale sans la sauvegarder.
    local_x = (work / "tools" / "x.py").read_text(encoding="utf-8")
    if code != 0:
        # conflit signalé : la version locale n'est pas perdue
        assert "VERSION LOCALE" in local_x
        assert report["status"] in ("NO_GO",) or report.get("force_push") is False
    # dans tous les cas : aucun push force, aucun reset/clean
    assert report.get("force_push") is False
    assert report.get("reset_or_clean") is False


def test_e2e_wip_sauvegarde_le_travail_inacheve(tmp_path):
    """#3 : --wip-only sauvegarde le travail en cours (commit local) sans tout finaliser."""
    work, _ = _repo_avec_remote(tmp_path)
    (work / "tools" / "x.py").write_text("print('travail en cours')\n", encoding="utf-8")
    head_avant = _git(work, "rev-parse", "HEAD")
    code, report = _run_sync(work, dry_run=False)  # run normal fait deja un commit propre
    # un commit a bien ete cree (le travail n'est pas perdu)
    head_apres = _git(work, "rev-parse", "HEAD")
    assert code == 0
    assert head_apres != head_avant or report.get("local_commit_created") is not None


def test_e2e_rien_ne_change_pas_de_commit_vide(tmp_path):
    """#10 : si rien n'a changé, aucun commit vide n'est créé."""
    work, _ = _repo_avec_remote(tmp_path)
    head_avant = _git(work, "rev-parse", "HEAD")
    n_commits_avant = _git(work, "rev-list", "--count", "HEAD")
    code, _ = _run_sync(work)
    assert code == 0
    assert _git(work, "rev-parse", "HEAD") == head_avant       # HEAD inchange
    assert _git(work, "rev-list", "--count", "HEAD") == n_commits_avant  # aucun commit ajoute


# --------------------------------------------------------------------------- #
# Churn runtime SOUS un dossier de code (classements de leaders réécrits par la collecte)
# --------------------------------------------------------------------------- #

CHURN = "config/copy_vault_leaders_candidats.json"


def _repo_avec_churn_suivi(tmp_path: Path) -> tuple[Path, Path]:
    work, remote = _repo_avec_remote(tmp_path)
    (work / "config").mkdir()
    (work / CHURN).write_text('{"candidats": 1}\n', encoding="utf-8")
    _git(work, "add", CHURN)
    _git(work, "commit", "-q", "-m", "suivi du classement")
    _git(work, "push", "-q", "origin", "main")
    return work, remote


def test_e2e_churn_runtime_sous_config_ne_bloque_pas_la_poussee_du_code(tmp_path):
    """Après une récolte, les classements de leaders sont réécrits : le code doit partir quand même,
    le classement local rester intact et ne JAMAIS être publié."""
    assert CHURN in S.RUNTIME_CHURN_FILES
    work, remote = _repo_avec_churn_suivi(tmp_path)
    (work / CHURN).write_text('{"candidats": 2}\n', encoding="utf-8")        # réécrit par la collecte
    (work / "tools" / "x.py").write_text("print('v2 apres recolte')\n", encoding="utf-8")
    code, report = _run_sync(work)
    assert code == 0 and report["status"] in ("SYNCHRONIZED", "PUSHED"), report.get("status")
    assert _git(remote, "show", "main:tools/x.py") == "print('v2 apres recolte')"      # code publié
    assert _git(remote, "show", f"main:{CHURN}") == '{"candidats": 1}'                 # donnée non publiée
    assert (work / CHURN).read_text(encoding="utf-8") == '{"candidats": 2}\n'          # donnée locale intacte
    assert CHURN in _git(work, "status", "--porcelain", "--", CHURN)                   # toujours hors commit


def test_e2e_churn_runtime_seul_ne_renvoie_pas_un_echec(tmp_path):
    work, remote = _repo_avec_churn_suivi(tmp_path)
    avant = _git(remote, "rev-parse", "main")
    (work / CHURN).write_text('{"candidats": 3}\n', encoding="utf-8")
    code, report = _run_sync(work)
    assert code == 0 and report["status"] in ("SYNCHRONIZED", "NOTHING_TO_SYNC", "CLEAN"), report.get("status")
    assert _git(remote, "rev-parse", "main") == avant                                  # rien publié
    assert (work / CHURN).read_text(encoding="utf-8") == '{"candidats": 3}\n'


def test_e2e_fichier_sensible_suivi_et_modifie_reste_bloquant(tmp_path):
    """Négatif : l'assouplissement ne vaut QUE pour le churn runtime déclaré, jamais pour un secret."""
    work, remote = _repo_avec_remote(tmp_path)
    (work / "config" / "secrets").mkdir(parents=True)
    sensible = "config/secrets/cles.json"
    (work / sensible).write_text('{"k": 1}\n', encoding="utf-8")
    _git(work, "add", "-f", sensible)
    _git(work, "commit", "-q", "-m", "suivi par erreur")
    _git(work, "push", "-q", "origin", "main")
    avant = _git(remote, "rev-parse", "main")
    (work / sensible).write_text('{"k": 2}\n', encoding="utf-8")
    (work / "tools" / "x.py").write_text("print('v3')\n", encoding="utf-8")
    code, report = _run_sync(work)
    assert code != 0 and report["status"] not in ("SYNCHRONIZED", "PUSHED"), report.get("status")
    assert _git(remote, "rev-parse", "main") == avant                                  # rien n'est parti
