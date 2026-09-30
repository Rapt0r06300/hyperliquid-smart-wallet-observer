"""Entrypoint du laboratoire RESEARCH_PARALLEL_V1 — LA ligne unique appelée par l'autopilot.

Lance le superviseur isolé. Charge les plugins qui se sont enregistrés (import du paquet `plugins`), fabrique
le contexte de données READ-ONLY à chaque tick, et tourne. Kill-switch mou via runtime/research_lab/DISABLED.
0 réseau obligatoire ici (les collecteurs LOT 1 alimentent la data) ; 0 /exchange, 0 clé, 0 ordre.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research_parallel import superviseur as SUP  # noqa: E402


def _charger_plugins() -> None:
    """Importe le paquet de plugins : chaque module s'enregistre au registre à l'import. Best-effort :
    un plugin qui casse à l'import ne doit pas empêcher le labo de tourner avec les autres."""
    try:
        import importlib
        import pkgutil
        from hl_observer.research_parallel import plugins as PK
        for m in pkgutil.iter_modules(PK.__path__):
            try:
                importlib.import_module("hl_observer.research_parallel.plugins." + m.name)
            except Exception as e:  # noqa: BLE001
                print("[lab] plugin %s non chargé: %s" % (m.name, e), flush=True)
    except Exception as e:  # noqa: BLE001 (paquet plugins absent = 0 plugin, labo inerte mais vivant)
        print("[lab] aucun plugin chargé: %s" % e, flush=True)


def contexte(root: Path) -> dict:
    """Contexte read-only pour un tick. LOT 0 : minimal ; LOT 1/2 l'enrichiront (data isolée + bbo_tape
    lu en SEULE LECTURE, jamais écrit). On ne touche jamais aux fichiers du main."""
    return {"root": str(root)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Laboratoire de recherche parallèle isolé (lecture seule).")
    ap.add_argument("--root", default=str(RACINE))
    ap.add_argument("--poll-s", type=float, default=60.0)
    ap.add_argument("--max-ticks", type=int, default=None)
    a = ap.parse_args(argv)
    _charger_plugins()
    root = Path(a.root)
    if SUP.est_desactive(root):
        print("[lab] DISABLED présent — labo à l'arrêt (rollback mou). Rien lancé.", flush=True)
        return 0
    print("[lab] démarrage RESEARCH_PARALLEL_V1 (isolé, read-only)", flush=True)
    res = SUP.boucle(root, poll_s=a.poll_s, contexte_fn=contexte, max_ticks=a.max_ticks)
    print("[lab] fin: %s" % res, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
