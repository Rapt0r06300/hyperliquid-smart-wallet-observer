"""AUD-057 — ÉCRITURE ATOMIQUE du registre PID des collecteurs.

Le bug audité : `superviseur_collecteurs` écrivait `collecteurs_pids.json` (PIDS_RELPATH) via un
`write_text` NON atomique, alors que le registre du LANCEUR passe, lui, par `registre_pids._ecrire_atomique`
(tmp + fsync + os.replace). Un crash EN COURS d'écriture pouvait donc laisser un JSON tronqué — et l'arrêt
CIBLÉ (`arreter_cible`) lit ce fichier pour savoir quels PID tuer : un registre partiel = des orphelins ou
un kill raté.

Ces tests prouvent l'atomicité :
  1. STRUCTUREL — les fonctions qui écrivent le registre PID n'utilisent plus de `write_text` direct ;
  2. le remplacement passe RÉELLEMENT par `os.replace(tmp -> cible)` ;
  3. après écriture, la cible est un JSON VALIDE et aucun fichier `.tmp` ne subsiste ;
  4. un ÉCHEC pendant le remplacement ne laisse JAMAIS de cible tronquée (et la panne est COMPTÉE).
"""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

from hl_observer.ops import superviseur_collecteurs as SC


def _spawn(pid: int):
    return lambda c, cwd: pid


# ------------------------------------------------------------------ 1. structurel

def test_aucun_write_text_direct_sur_le_registre_pid():
    """Les trois sites d'écriture du registre PID (demarrer_tous / demarrer_un / enregistrer_pids)
    ne doivent plus écrire la cible via `write_text` (source unique d'écriture ATOMIQUE)."""
    for fn in (SC.demarrer_tous, SC.demarrer_un, SC.enregistrer_pids):
        src = inspect.getsource(fn)
        assert "write_text" not in src, (
            "%s écrit le registre PID sans passer par l'écriture atomique" % fn.__name__)


# ------------------------------------------------------------------ 2. os.replace

def test_ecriture_passe_par_os_replace_sur_la_cible(tmp_path, monkeypatch):
    vus: list[tuple[str, str]] = []
    vrai_replace = os.replace

    def espion(src, dst, *a, **k):
        vus.append((str(src), str(dst)))
        return vrai_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", espion)
    SC.demarrer_tous(tmp_path, spawner=_spawn(111), profil="core", procs=[])

    cible = tmp_path / SC.PIDS_RELPATH
    sur_cible = [(src, dst) for src, dst in vus if dst == str(cible)]
    assert sur_cible, "os.replace n'a jamais été appelé sur le registre PID (écriture non atomique)"
    assert all(src.endswith(".tmp") for src, _dst in sur_cible), "le remplacement doit venir d'un tmp"


# ------------------------------------------------------------------ 3. JSON valide, zéro tmp résiduel

def test_registre_ecrit_est_un_json_valide_sans_tmp_residuel(tmp_path):
    r = SC.demarrer_tous(tmp_path, spawner=_spawn(4321), profil="core", procs=[])
    cible = tmp_path / SC.PIDS_RELPATH
    assert cible.is_file()

    data = json.loads(cible.read_text(encoding="utf-8"))       # JSON complet -> jamais tronqué
    assert set(data.get("pids", {})) >= set(SC.COLLECTEURS_CORE)
    assert all(pid == 4321 for pid in data["pids"].values())
    assert set(r["pids"]) >= set(SC.COLLECTEURS_CORE)
    # écriture atomique terminée par os.replace : aucun temporaire ne subsiste
    assert list(cible.parent.glob("*.tmp")) == []


# ------------------------------------------------------------------ 4. échec = aucune cible partielle

def test_echec_pendant_le_remplacement_ne_laisse_pas_de_cible_partielle(tmp_path, monkeypatch):
    SC.PANNES_INTERNES.pop("pids_inecrivable", None)

    def crash(src, dst, *a, **k):
        raise OSError("crash simulé pendant os.replace")

    monkeypatch.setattr(os, "replace", crash)
    SC.demarrer_tous(tmp_path, spawner=_spawn(222), profil="core", procs=[])

    cible = tmp_path / SC.PIDS_RELPATH
    # un crash pendant l'écriture ne peut PAS créer un registre PID tronqué : la cible n'existe pas
    assert not cible.exists(), "une écriture interrompue a laissé un registre PID partiel"
    # la panne interne est COMPTÉE (jamais avalée en silence)
    assert SC.PANNES_INTERNES.get("pids_inecrivable", 0) >= 1
