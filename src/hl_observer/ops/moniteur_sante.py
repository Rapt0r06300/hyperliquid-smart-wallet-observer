"""[LANCEUR item 12] Moniteur de santé — boucle qui RAFRAÎCHIT en place le tableau de santé (zone
dynamique) et APPEND une ligne horodatée au journal, à chaque passe.

Compose les briques : preuve_de_vie (heartbeats réels) + registre_pids (PID réels) +
tableau_sante_collecteurs (rendu compact + journal). events/s se calcule entre deux passes.

`python -m hl_observer.ops.moniteur_sante [racine] [--passes N] [--intervalle S]`. Tout est injectable
(lecteur d'état, horloge, sleep, sortie) → testable sans réseau ni temps réel. 0 ordre, 0 réseau.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from hl_observer.ops.preuve_de_vie import (SOURCES_HARVEST, SourceAttendue, lire_heartbeats_reels,
                                           metriques_depuis_heartbeats)
from hl_observer.ops.preuve_de_vie import _pid_vivant_reel as _pid_vivant
from hl_observer.ops.registre_pids import lire_registre
from hl_observer.ops.tableau_sante_collecteurs import Tableau, construire_tableau, format_tableau, ligne_journal

JOURNAL_RELPATH = Path("runtime") / "logs" / "sante_journal.log"


def lire_etat_reel(root: str | Path, sources: Sequence[SourceAttendue]) -> tuple[dict, dict, dict]:
    """Lit heartbeats (canoniques) + PID (registre lanceur) + métriques. 0 réseau. Une source sans
    heartbeat reste honnêtement absente."""
    hbs = lire_heartbeats_reels(root, sources)
    reg = lire_registre(root)
    pids = {k: int(v) for k, v in dict(reg.get("collecteurs") or {}).items() if isinstance(v, int)}
    # feed_quality RÉEL (item 2/9) : gaps/reconnects/stale/hors-ordre écrits par les collecteurs, lus du
    # heartbeat — le moniteur affiche donc l'état de flux réel, jamais un tableau vert en trompe-l'œil.
    # On traduit les clés de readiness (gaps_critiques/stale/hors_ordre) vers les clés canoniques du
    # tableau (gaps/stale_events/out_of_order/reconnects) pour qu'elles remontent réellement.
    brut = metriques_depuis_heartbeats(hbs)
    metriques: dict[str, Any] = {}
    for nom, m in brut.items():
        fusion = dict(m)
        fusion.setdefault("gaps", int(m.get("gaps_critiques", 0)))
        fusion.setdefault("reconnects", int(m.get("reconnects", 0)))
        fusion.setdefault("stale_events", int(bool(m.get("stale", False))))
        fusion.setdefault("out_of_order", int(m.get("hors_ordre", 0)))
        metriques[nom] = fusion
    return hbs, pids, metriques


def _append_journal(chemin: Path, ligne: str) -> None:
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("a", encoding="utf-8") as fh:
            fh.write(ligne + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass


def une_passe(root: str | Path, sources: Sequence[SourceAttendue], *, now_ms: float,
              pid_vivant: Callable[[int], bool], precedent: Mapping[str, Mapping[str, float]] | None,
              horodatage: str, lecteur: Callable[[], tuple[dict, dict, dict]] | None = None) -> Tableau:
    hbs, pids, metriques = (lecteur() if lecteur is not None else lire_etat_reel(root, sources))
    return construire_tableau(sources, hbs, pids, metriques, now_ms=now_ms, pid_vivant=pid_vivant,
                              precedent=precedent, horodatage=horodatage)


def boucle(root: str | Path, sources: Sequence[SourceAttendue] = SOURCES_HARVEST, *, passes: int,
           intervalle_s: float, horloge: Callable[[], float], dormir: Callable[[float], None],
           sortie: Callable[[str], None], lecteur: Callable[[], tuple[dict, dict, dict]] | None = None,
           pid_vivant: Callable[[int], bool] | None = None,
           horodateur: Callable[[float], str] | None = None) -> Tableau:
    """N passes : à chaque passe, rafraîchit la zone (sortie) + append une ligne au journal. Rend le
    dernier tableau. Injectable → testable."""
    pv = pid_vivant or _pid_vivant
    horo = horodateur or (lambda t: "t=%d" % int(t))
    journal = Path(root) / JOURNAL_RELPATH
    precedent: Mapping[str, Mapping[str, float]] | None = None
    dernier: Tableau = Tableau()
    for i in range(max(1, int(passes))):
        t = horloge()
        dernier = une_passe(root, sources, now_ms=t * 1000.0, pid_vivant=pv, precedent=precedent,
                            horodatage=horo(t), lecteur=lecteur)
        sortie(format_tableau(dernier))               # zone dynamique (ré-affichée en place)
        _append_journal(journal, ligne_journal(dernier))   # journal append-only horodaté
        precedent = dernier.snapshot
        if i < passes - 1:
            dormir(intervalle_s)
    return dernier


def _sortie_console(texte: str) -> None:
    # zone dynamique : on efface l'écran puis on ré-affiche (cls sous Windows, ANSI ailleurs)
    if os.name == "nt":
        os.system("cls")  # noqa: S605,S607 — commande fixe, pas d'entrée utilisateur
    else:
        print("\033[2J\033[H", end="")
    print(texte, flush=True)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import time
    p = argparse.ArgumentParser(description="Moniteur de sante des collecteurs (lecture seule).")
    p.add_argument("racine", nargs="?", default=".")
    p.add_argument("--passes", type=int, default=10_000)      # ~continu ; Ctrl-C pour arrêter
    p.add_argument("--intervalle", type=float, default=2.0)
    args = p.parse_args(argv)

    def _horo(t: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))

    try:
        boucle(args.racine, passes=args.passes, intervalle_s=args.intervalle,
               horloge=time.time, dormir=time.sleep, sortie=_sortie_console, horodateur=_horo)
    except KeyboardInterrupt:
        print("\n[moniteur-sante] arret.", flush=True)
    return 0


__all__ = ["JOURNAL_RELPATH", "lire_etat_reel", "une_passe", "boucle", "main"]


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
