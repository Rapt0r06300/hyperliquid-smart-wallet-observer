"""Verrou de PID : un passage LONG (plus de 6 h) garde son verrou tant que c'est le même processus vivant.

26/11/2026 : un scellage manuel lancé à 17:01 dure toute la nuit. Son verrou, jamais rafraîchi, devenait
« périmé » à 23:01 alors que son PID vivait : le certificateur en continu l'aurait pris, et deux écrivains
auraient tourné sur SOURCES_TRAITEES.json. Un PID réutilisé après un redémarrage, lui, est né APRÈS le verrou.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import verrou_pid as V  # noqa: E402


def _verrou(chemin: Path, pid: int, ts: float) -> None:
    chemin.write_text(json.dumps({"pid": pid, "ts": ts}), encoding="utf-8")


def test_un_passage_long_garde_son_verrou(tmp_path, monkeypatch):
    f = tmp_path / "v.lock"
    _verrou(f, os.getpid(), time.time() - 7 * 3600)
    monkeypatch.setattr(V, "meme_processus", lambda pid, depuis: True)       # né avant le verrou
    obtenu, mot = V.prendre(f, quoi="un scellage")
    assert obtenu is False and "passage long" in mot
    assert json.loads(f.read_text())["pid"] == os.getpid()                    # verrou intact


def test_un_pid_reutilise_ne_garde_pas_le_verrou(tmp_path, monkeypatch):
    f = tmp_path / "v.lock"
    _verrou(f, os.getpid(), time.time() - 7 * 3600)
    monkeypatch.setattr(V, "meme_processus", lambda pid, depuis: False)      # né après : PID réutilisé
    obtenu, mot = V.prendre(f, quoi="un scellage")
    assert obtenu is True and "PERIME" in mot


def test_indecidable_garde_l_ancienne_regle(tmp_path, monkeypatch):
    f = tmp_path / "v.lock"
    _verrou(f, os.getpid(), time.time() - 7 * 3600)
    monkeypatch.setattr(V, "meme_processus", lambda pid, depuis: None)
    assert V.prendre(f, quoi="un scellage")[0] is True                        # comme avant le correctif


def test_meme_processus_reconnait_le_processus_courant():
    assert V.meme_processus(os.getpid(), time.time()) is True                 # né avant « maintenant »
    assert V.meme_processus(os.getpid(), 0.0) is False                        # né après 1970
