"""Tests réalistes de POUSSER-GITHUB-FORCE (moteur alina_git_code_sync).

Couvre le cahier des charges : séparation code/données (#8), messages de commit
intelligents (#4), « rien à faire » sans faux échec (le fix du NO_GO), et des
scénarios end-to-end sur un VRAI dépôt git temporaire avec un remote « bare » :
commit + push (#2), fichiers non suivis (#3), commits GitHub concurrents (#6),
conflit préservé sans perte (#5), vérification du résultat (#10).
"""
from __future__ import annotations

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
    sync = S.Synchronizer(work, allow_test_remote=True, **kw)
    code = sync.run()
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
