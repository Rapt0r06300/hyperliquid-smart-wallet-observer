"""LE LANCEUR TOUT-TESTER — ce qu'il annonce doit exister (21/07).

Le `.cmd` ne faisait que quatre choses : `cd`, `PYTHONPATH`, lancer, `pause`. Tout le reste
était supposé — Python présent, bonne version, projet au bon endroit, aucun interrupteur
d'exécution réelle armé, RECAP réellement réécrit par CE run.

Ces tests verrouillent le contrat du lanceur. Ils tournent sous Linux comme sous Windows :
ils lisent le `.cmd` comme un texte, ils ne l'exécutent pas.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.tout_tester import OPTIONS, main

CMD = Path(__file__).resolve().parents[1] / "TOUT-TESTER.cmd"


@pytest.fixture(scope="module")
def txt() -> str:
    return CMD.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def corps(txt: str) -> str:
    """Le code, sans l'en-tête de documentation."""
    return txt.split("setlocal EnableDelayedExpansion", 1)[1]


# ─────────────── « mention ≠ porte », appliqué au lanceur lui-même ───────────────

def test_aucune_option_annoncee_n_est_un_fantome(txt: str):
    """Une option écrite dans l'aide que personne ne gère est un mensonge à l'utilisateur :
    il croit avoir changé le comportement du run, et il lit un RECAP qui répond à une autre
    question. Les seules options du LANCEUR sont celles qu'il consomme lui-même."""
    annoncees = {o for o in re.findall(r"^REM\s+(--[a-z][a-z-]+)", txt, re.M)}
    du_lanceur = {"--sans-pause", "--ouvrir"}
    fantomes = annoncees - set(OPTIONS) - du_lanceur
    assert not fantomes, "options annoncees que personne ne gere : %s" % sorted(fantomes)


def test_les_options_du_lanceur_sont_bien_retirees_avant_le_python(corps: str):
    """`--sans-pause` et `--ouvrir` n'existent pas côté Python : les transmettre ferait
    échouer le run avec « option inconnue »."""
    for o in ("--sans-pause", "--ouvrir"):
        assert '"%%~A"=="' + o + '"' in corps, "%s doit etre consommee par le .cmd" % o
    assert "--rapide" not in corps.split("set \"ARGS=\"", 1)[-1].split("python \"", 1)[0], (
        "les options du Python ne doivent PAS etre interpretees par le .cmd : "
        "deux listes d'options finissent toujours par diverger")


def test_une_option_inconnue_est_refusee_et_non_avalee():
    assert main(["--nimportequoi"]) == 2
    assert main(["--aide"]) == 0


# ─────────────── sécurité : la barrière avant tout le reste ───────────────

def test_le_lanceur_refuse_un_interrupteur_d_execution_reelle(corps: str):
    for var in ("REAL_MAINNET_TRADING", "HYPERSMART_REAL_TRADING", "ENABLE_REAL_ORDERS"):
        assert var in corps, "%s doit etre verifiee avant de lancer quoi que ce soit" % var
    assert "exit /b 5" in corps, "un arret de securite doit avoir son propre code de sortie"


def test_le_lanceur_refuse_une_cle_privee_dans_l_environnement(corps: str):
    for var in ("PRIVATE_KEY", "MNEMONIC", "SEED_PHRASE", "WALLET_SECRET"):
        assert var in corps


def test_le_lanceur_pose_lecture_seule_pour_le_processus_fils(corps: str):
    assert "HYPERSMART_READ_ONLY=1" in corps
    assert "HYPERSMART_PAPER_ONLY=1" in corps


def test_la_banniere_lecture_seule_precede_le_premier_calcul(corps: str):
    i_ban = corps.find("LECTURE SEULE")
    i_py = corps.find("python -c")
    assert 0 <= i_ban < i_py, "la banniere doit s'afficher AVANT tout appel a Python"


# ─────────────── pré-vol et robustesse ───────────────

def test_le_pre_vol_verifie_python_sa_version_et_le_projet(corps: str):
    assert "where python" in corps
    assert "sys.version_info>=(3,10)" in corps, "le code utilise la syntaxe `X | None`"
    assert "tools\\tout_tester.py" in corps and "%PROJ%\\src" in corps


def test_les_pieges_connus_du_projet_sont_neutralises(corps: str):
    """`.pyc` périmés à travers le mount, sortie bufferisée, accents du RECAP."""
    assert "PYTHONDONTWRITEBYTECODE=1" in corps
    assert "PYTHONUNBUFFERED=1" in corps
    assert "PYTHONIOENCODING=utf-8" in corps and "chcp 65001" in corps


def test_le_chemin_avec_espace_est_toujours_entre_guillemets(corps: str):
    """« Projet invest » contient un espace : un `%PROJ%` nu casse tout."""
    nus = [ln.strip() for ln in corps.splitlines()
           if re.search(r"(?<!\")%PROJ%(?!\")", ln)
           and not ln.strip().upper().startswith("REM")
           and "set \"" not in ln and "echo" not in ln.lower()
           and "findstr" not in ln and "%PROJ:~" not in ln]
    assert not nus, "%%PROJ%% doit etre entre guillemets : %s" % nus[:3]


def test_le_verrou_anti_double_lancement_est_toujours_relache(corps: str):
    """Un verrou qui survit à un échec bloque tous les lancements suivants."""
    assert corps.count('del "%LOCK%"') >= 3, (
        "le verrou doit tomber sur CHAQUE sortie : securite, cle, et fin de run")


def test_le_code_de_sortie_est_propage(corps: str):
    assert "endlocal & exit /b %CODE%" in corps


# ─────────────── traçabilité ───────────────

def test_le_recap_precedent_est_archive_jamais_ecrase(corps: str):
    assert "logs-audit\\recaps" in corps and "copy /y" in corps


def test_un_recap_perime_est_signale(corps: str):
    """Le pire échec silencieux : le run plante, le RECAP d'hier reste en place, et on le
    lit en croyant lire celui d'aujourd'hui."""
    assert "PERIME" in corps and "LastWriteTime" in corps
    assert "n'a PAS ete reecrit par ce run" in corps


def test_un_recap_vide_est_signale(corps: str):
    assert '"!TAILLE!"=="0"' in corps, "un RECAP de 0 octet est un echec, pas un succes"


def test_l_etat_git_est_capture(corps: str):
    """5 jours de travail non commité avaient été découverts le 14/07 parce que personne
    ne regardait. L'audit juge le disque ; il doit dire ce que le disque a de plus que git."""
    assert "rev-parse --short HEAD" in corps
    assert "git status --porcelain" in corps
    assert "juge le DISQUE" in corps


def test_les_logs_sont_conserves_mais_bornes(corps: str):
    assert "skip=30" in corps, "on garde les 30 derniers logs : conserver sans noyer"


# ─────────────── les 40 améliorations sont réellement dans le code ───────────────

def test_les_quarante_ameliorations_sont_marquees_dans_le_code(corps: str):
    """L'en-tête promet 40 améliorations numérotées. Chacune doit être repérable dans le
    code — sinon la liste devient un catalogue d'intentions, ce que ce projet appelle une
    « tombe en prose »."""
    manquants = [n for n in range(1, 41)
                 if not re.search(r"---\s*[\d/]*\b%02d\b" % n, corps)]
    assert not manquants, "ameliorations annoncees mais absentes du code : %s" % manquants
