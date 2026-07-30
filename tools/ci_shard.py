"""Découpage DÉTERMINISTE de la suite de tests en shards pour la CI (pur, 0 réseau).

La CI échouait pour une raison simple : `pytest -q` lance **6 383 tests** sous un `timeout-minutes: 15`.
La réponse facile aurait été de désactiver des tests. La bonne réponse est de les **répartir** : chaque shard
tourne en parallèle, aucun test n'est perdu, et l'union des shards est exactement la suite complète.

Deux propriétés garanties, toutes deux testées :

* **Partition** — chaque fichier de test appartient à exactement un shard. Ni doublon (temps gaspillé), ni
  oubli (un test qui ne tourne plus est pire qu'un test lent).
* **Déterminisme** — le même `(index, total)` rend toujours la même liste, quel que soit l'ordre du système
  de fichiers. Une CI dont le contenu varie d'un run à l'autre ne prouve rien.

Usage : `python tools/ci_shard.py <index 1-based> <total>` → chemins séparés par des espaces.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

RACINE = Path(__file__).resolve().parents[1]
DOSSIER_TESTS = "tests"
MOTIF = "test_*.py"


def fichiers_de_test(racine: Path | str = RACINE, *, dossier: str = DOSSIER_TESTS,
                     motif: str = MOTIF) -> list[str]:
    """Tous les fichiers de test, triés — le tri est ce qui rend le découpage reproductible."""
    base = Path(racine) / dossier
    if not base.is_dir():
        return []
    return sorted(p.as_posix() for p in (Path(dossier) / f.name for f in base.glob(motif)))


def shard(fichiers: Sequence[str], index: int, total: int) -> list[str]:
    """Shard `index` (1-based) sur `total`. Répartition en round-robin : les fichiers lents se répartissent
    au lieu de s'accumuler dans le dernier shard."""
    if total < 1:
        raise ValueError("total doit valoir au moins 1")
    if not 1 <= index <= total:
        raise ValueError("index doit etre entre 1 et %d" % total)
    return [f for i, f in enumerate(fichiers) if i % total == (index - 1)]


def verifier_partition(fichiers: Sequence[str], total: int) -> dict[str, object]:
    """Contrôle explicite : l'union des shards redonne la suite complète, sans recouvrement."""
    morceaux = [shard(fichiers, i, total) for i in range(1, total + 1)]
    plat = [f for m in morceaux for f in m]
    return {"n_fichiers": len(fichiers), "n_shards": total,
            "tailles": [len(m) for m in morceaux],
            "sans_doublon": len(plat) == len(set(plat)),
            "complet": sorted(plat) == sorted(fichiers),
            "partition_valide": len(plat) == len(set(plat)) and sorted(plat) == sorted(fichiers)}


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Shard deterministe de la suite de tests.")
    p.add_argument("index", type=int, help="index du shard, 1-based")
    p.add_argument("total", type=int, help="nombre total de shards")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--verifier", action="store_true", help="affiche le controle de partition et sort")
    a = p.parse_args(list(argv) if argv is not None else None)
    fichiers = fichiers_de_test(a.root)
    if a.verifier:
        print(verifier_partition(fichiers, a.total))
        return 0
    morceau = shard(fichiers, a.index, a.total)
    if not morceau:
        # un shard vide ne doit pas faire echouer la CI : on le dit et on rend un code 0
        print("", end="")
        return 0
    sys.stdout.write(" ".join(morceau))
    return 0


__all__ = ["fichiers_de_test", "shard", "verifier_partition", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
