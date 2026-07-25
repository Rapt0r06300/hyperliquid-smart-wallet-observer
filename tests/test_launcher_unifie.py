"""LANCEUR UNIQUE (2026-07-25) — `LANCER_HYPERSMART.cmd` absorbe tous les anciens .cmd racine.

Ce test garde la migration : un seul .cmd actif, un dispatcher qui route CHAQUE sous-commande,
aucune baisse du no-real-trade, et une archive legale complete (chaque ancien .cmd copie en
.cmd.txt avec SHA-256 verifiable). « Rien n'echappe aux tests. »
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
LANCEUR = RACINE / "LANCER_HYPERSMART.cmd"
ARCHIVE = RACINE / "docs" / "archive" / "legacy_cmd" / "2026-07-25"

CANONIQUES = ["status", "stop", "restart", "restart-userfills", "collectors", "report",
              "test", "audit", "replay", "moisson", "verify-oos", "github-push", "menu", "self-test"]


def _txt() -> str:
    return LANCEUR.read_text(encoding="utf-8", errors="ignore")


# ------------------------------------------------------------------ 1. dispatcher

def test_le_lanceur_a_un_dispatcher_et_un_autopilot():
    t = _txt()
    assert 'if not "%~1"=="" goto :dispatch' in t, "double-clic sans argument doit tomber sur l'AUTOPILOT"
    assert re.search(r'(?m)^:autopilot\b', t)
    assert re.search(r'(?m)^:dispatch\b', t)
    assert re.search(r'(?m)^:fin\b', t)


@pytest.mark.parametrize("sub", CANONIQUES)
def test_chaque_sous_commande_canonique_est_routee(sub):
    """Le dispatcher doit avoir une ligne `if /I "%SUB%"=="<sub>" goto :cmd_...` ET la cible existe."""
    t = _txt()
    m = re.search(r'if /I "%%SUB%%"=="%s"\s+goto :(\S+)' % re.escape(sub), t)
    assert m, "sous-commande %r absente du dispatcher" % sub
    cible = m.group(1)
    assert re.search(r'(?m)^:%s\b' % re.escape(cible), t), "label %r introuvable pour %r" % (cible, sub)


def test_les_collecteurs_sont_une_source_unique_reutilisee():
    """L'autopilot ET `collectors` appellent la MEME sous-routine :demarrer_collecteurs
    (pas de duplication des lignes 'start ... boucle_collecteur')."""
    t = _txt()
    assert re.search(r'(?m)^:demarrer_collecteurs\b', t)
    assert t.count("call :demarrer_collecteurs") >= 2, "autopilot + collectors doivent la reutiliser"


# ------------------------------------------------------------------ 2. securite / no-real-trade

def test_no_real_trade_preserve():
    t = _txt()
    assert "HL_ENV=paper" in t
    assert "HL_ENABLE_MAINNET_EXECUTION=0" in t
    assert "HL_ENABLE_TESTNET_EXECUTION=0" in t
    assert "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW" in t
    assert "/exchange" not in t, "aucun endpoint d'execution reelle dans le lanceur"


def test_pas_de_fenetre_cachee_ni_kill_global():
    t = _txt()
    assert "WindowStyle Hidden" not in t, "les processus du lanceur ne se cachent pas (test single_launcher)"
    # aucun kill global de python/cmd : on ne cible que par ligne de commande du projet
    assert "taskkill /im python" not in t.lower()
    assert "taskkill /f /im python" not in t.lower()


def test_github_push_jamais_automatiquement_force():
    """github-push normal = push simple ; --force seulement si demande EXPLICITEMENT."""
    t = _txt()
    m = re.search(r'(?ms)^:cmd_github\b.*?(?=^goto :fin)', t)
    assert m, "bloc :cmd_github introuvable"
    bloc = m.group(0)
    assert 'if /I "%~2"=="--force"' in bloc, "le force doit etre garde par --force explicite"


def test_verrou_instance_unique_et_registre_pid():
    t = _txt()
    assert "8794" in t and "Test-NetConnection" in t, "verrou d'instance unique (UI deja active -> refus)"
    assert "launcher_pids.json" in t, "registre PID/run_id du lanceur"


# ------------------------------------------------------------------ 3. archive legale complete

def test_archive_existe_avec_manifeste_et_sommes():
    assert (ARCHIVE / "MANIFEST_MIGRATION.md").exists()
    assert (ARCHIVE / "SHA256SUMS.txt").exists()
    txts = list(ARCHIVE.glob("*.cmd.txt"))
    assert len(txts) >= 28, "les 28 anciens .cmd racine doivent etre archives en .cmd.txt"


def test_chaque_archive_a_un_sha256_valide():
    sommes = (ARCHIVE / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert sommes, "SHA256SUMS.txt ne doit pas etre vide"
    for ligne in sommes:
        sha, nom = ligne.split("  ", 1)
        f = ARCHIVE / nom
        assert f.exists(), "archive manquante : %s" % nom
        calc = hashlib.sha256(f.read_bytes()).hexdigest()
        assert calc == sha, "SHA-256 divergent pour %s" % nom


def test_le_lanceur_unique_n_est_pas_archive():
    """On archive les ABSORBES, jamais le lanceur lui-meme."""
    assert not (ARCHIVE / "LANCER_HYPERSMART.cmd.txt").exists()


# ------------------------------------------------------------------ 4. racine nettoyee

def test_la_racine_ne_contient_que_le_lanceur_unique():
    """L'OBJECTIF de la migration : un seul .cmd ACTIF en racine. Seule exception demandee par
    Flo : POUSSER-GITHUB-FORCE.cmd, garde a part. Tout le reste est absorbe en sous-commandes."""
    cmd_racine = sorted(p.name for p in RACINE.glob("*.cmd"))
    assert cmd_racine == ["LANCER_HYPERSMART.cmd", "POUSSER-GITHUB-FORCE.cmd"], (
        "la racine ne doit contenir que le lanceur unique (+ POUSSER-GITHUB-FORCE.cmd) ; trouve : %r"
        % cmd_racine)
