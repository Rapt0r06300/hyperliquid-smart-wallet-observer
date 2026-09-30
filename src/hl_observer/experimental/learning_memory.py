"""AUD-132 — memoire d'apprentissage INTER-RUN (append-only, persistee).

Une config testee et son OUTCOME sont ecrits dans une memoire append-only sur disque, qu'un run
SUIVANT relit : on n'oublie pas ce qu'on a appris entre deux lancements. Ajout seulement ; le plus
recent gagne a la lecture. Aucune donnee fabriquee, read-only sur les runs passes.
"""
from __future__ import annotations

import json
from pathlib import Path

FICHIER = "learning_memory.jsonl"


def enregistrer_apprentissage(dossier: str | Path, *, cle: str, outcome: dict) -> None:
    d = Path(dossier)
    d.mkdir(parents=True, exist_ok=True)
    with (d / FICHIER).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"cle": str(cle), "outcome": outcome}, sort_keys=True) + "\n")


def lire_memoire(dossier: str | Path) -> dict:
    """{cle: dernier_outcome} agrege sur TOUS les runs passes (le plus recent gagne)."""
    p = Path(dossier) / FICHIER
    mem: dict = {}
    if p.is_file():
        for ligne in p.read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                e = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            mem[e["cle"]] = e["outcome"]
    return mem


def deja_teste(dossier: str | Path, cle: str) -> bool:
    return str(cle) in lire_memoire(dossier)


__all__ = ["enregistrer_apprentissage", "lire_memoire", "deja_teste", "FICHIER"]
