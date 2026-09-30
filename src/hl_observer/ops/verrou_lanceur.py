"""[LANCEUR item 11] Verrou d'instance du LANCEUR — CLI mince réutilisant le verrou canonique
`collection.verrou_instance` (mutex nommé Windows kernel + lockfile TTL). PAS un doublon : c'est une
porte d'entrée `.cmd` avec un TTL adapté au warmup (le seul contrôle du port 8794 ne suffit pas avant que
l'UI ne lie le port).

Deux double-clics simultanés ne lancent JAMAIS deux récoltes : le premier acquiert (mutex atomique +
lockfile frais), le second est refusé tant que le verrou est frais (fenêtre de warmup) ou que l'UI est up
(contrôle du port, côté .cmd). 0 réseau, 0 ordre.
"""
from __future__ import annotations

from pathlib import Path

from hl_observer.collection import verrou_instance as VI

NOM = "lanceur_instance"
# fenêtre de warmup : le lockfile du lanceur (non rafraîchi pendant le démarrage) reste valide 10 min —
# largement au-delà du warmup READY_CORE. Au-delà, un crash est repris ; un run réel a lié le port 8794
# (le .cmd bloque alors par le contrôle de port).
TTL_WARMUP_MS = 600_000.0


def acquerir_lanceur(root: str | Path, *, now_ms: float | None = None,
                     ttl_ms: float = TTL_WARMUP_MS) -> tuple[bool, dict]:
    return VI.acquerir(Path(root), NOM, now_ms=now_ms, ttl_ms=ttl_ms)


def liberer_lanceur(root: str | Path, info: dict | None = None) -> None:
    # à l'arrêt, on retire le lockfile du lanceur (le lanceur est autoritaire sur son cycle de vie).
    p = Path(root) / "runtime" / "data" / ("%s.lock" % NOM)
    try:
        p.unlink()
    except OSError:
        import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
        _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Verrou d'instance du lanceur (item 11).")
    p.add_argument("action", choices=("acquerir", "liberer"))
    p.add_argument("racine", nargs="?", default=".")
    args = p.parse_args(argv)
    if args.action == "acquerir":
        ok, info = acquerir_lanceur(args.racine)
        if ok:
            print("VERROU_LANCEUR_ACQUIS run_id=%s" % info.get("run_id"), flush=True)
            return 0
        print("VERROU_LANCEUR_OCCUPE : une recolte demarre/tourne deja (%s). Un seul lancement a la fois." %
              info.get("raison"), flush=True)
        return 3
    liberer_lanceur(args.racine)
    print("VERROU_LANCEUR_LIBERE", flush=True)
    return 0


__all__ = ["NOM", "TTL_WARMUP_MS", "acquerir_lanceur", "liberer_lanceur", "main"]
