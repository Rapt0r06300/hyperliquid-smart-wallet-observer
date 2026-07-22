"""RECHERCHE PARALLÈLE — OPT-IN (`TOUT_TESTER_RECHERCHE_PARALLELE=1`), 22/07.

Chaque module de recherche (carry, copy, arbitrage) est INDÉPENDANT : on peut les chercher en
même temps pour diviser le temps mur. Mais on ne refait PAS l'erreur du `ProcessPoolExecutor` qui
deadlockait (workers non tuables, tube partagé, 0 % CPU, Ctrl-C sans effet). Ici :

  * de VRAIS sous-processus isolés (`subprocess.Popen`), un par module ;
  * chaque sortie va dans un FICHIER dédié — AUCUN tube partagé, donc aucun blocage possible ;
  * chacun a déjà son budget interne (la boucle /goal s'arrête au budget) ; le `wait` du parent
    n'est qu'un filet, et comme `chercher` ne spawn rien, un simple `kill` suffit (feuille) ;
  * les résultats sont relus depuis les fichiers, la sortie est affichée GROUPÉE par module.

Le défaut reste SÉQUENTIEL (HUD en direct + ETA mesurée). Ce module ne s'active que sur demande.
REPLAY-only : les sous-processus rejouent des données enregistrées, aucun ordre, aucun réseau.
"""
from __future__ import annotations

import json as _json
import subprocess as _sp
import sys as _sys
import time as _t
from pathlib import Path
from typing import Any, Iterable

#: le corps du sous-processus : chercher UN module et sérialiser son résultat dans un fichier.
_GABARIT = (
    "import json;from hl_observer.backtesting.recherche_scenario import chercher,grille_large;"
    "json.dump(chercher({root!r},strategie={strat!r},configs=grille_large(),max_essais={me!r},"
    "budget_s={bs!r},s_arreter_au_premier=False,raffiner=True),"
    "open({out!r},'w',encoding='utf-8'),default=str)"
)


def remplir_en_parallele(root: str | Path, budget_s: float | None, max_essais: int | None,
                         modules: Iterable[str], resultats: dict[str, Any]) -> dict[str, Any]:
    """Lance chaque module en sous-processus isolé, collecte les résultats dans `resultats`.

    Retourne `resultats` (mêmes clés que la recherche séquentielle). Un module dont le
    sous-processus n'écrit rien (crash, timeout) devient ERREUR — jamais un faux résultat."""
    base = Path(root) / "runtime" / "replay"
    base.mkdir(parents=True, exist_ok=True)
    lances = []
    for strat in modules:
        out = base / ("_par_%s.json" % strat)
        log = base / ("_par_%s.log" % strat)
        try:
            out.unlink()
        except OSError:
            pass
        code = _GABARIT.format(root=str(root), strat=strat, me=max_essais, bs=budget_s, out=str(out))
        fh = open(log, "w", encoding="utf-8")
        proc = _sp.Popen([_sys.executable, "-c", code], stdout=fh, stderr=_sp.STDOUT,
                         start_new_session=True)
        lances.append((strat, proc, out, log, fh))
    print("=== %d modules cherches EN PARALLELE (sous-processus isoles, tuables) ==="
          % len(lances), flush=True)
    fin = _t.time() + float(budget_s or 7200.0) * 2.0 + 180.0     # filet global très large
    for strat, proc, out, log, fh in lances:
        try:
            proc.wait(timeout=max(1.0, fin - _t.time()))
        except _sp.TimeoutExpired:
            proc.kill()                        # process FEUILLE (chercher ne spawn rien) -> kill simple
        try:
            fh.close()
        except OSError:
            pass
        print("=== module %s ===" % strat, flush=True)
        try:
            print(log.read_text(encoding="utf-8"), end="", flush=True)   # sortie GROUPÉE, lisible
        except OSError:
            pass
        try:
            resultats[strat] = _json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            resultats[strat] = {"statut": "ERREUR", "strategie": strat,
                                "motif": "sous-processus sans resultat", "essais": []}
    return resultats


__all__ = ["remplir_en_parallele"]
