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

#: le corps du sous-processus : chercher UN module (via l'AIGUILLAGE, donc carry -> sa vraie grille)
#: et sérialiser son résultat dans un fichier.
_GABARIT = (
    "import json;from hl_observer.backtesting.recherche_scenario import chercher_module;"
    "json.dump(chercher_module({root!r},{strat!r},budget_s={bs!r},max_essais={me!r}),"
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
            import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
            _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
        code = _GABARIT.format(root=str(root), strat=strat, me=max_essais, bs=budget_s, out=str(out))
        fh = open(log, "w", encoding="utf-8")
        # MEME FAMILLE QUE rattrapage_complet.py, CORRIGEE LE MEME JOUR (20/11/2026), mais
        # ici MULTIPLIEE PAR LA BOUCLE : le journal etait ouvert AVANT `Popen`, et les
        # descripteurs deja ouverts sont retenus dans `lances`. Si la creation d un
        # processus echoue -- commande absente, ou machine saturee ou Windows ne peut plus
        # creer de processus -- la fonction sort en levant et PLUS AUCUN des journaux
        # precedents n est ferme. Sous Windows un descripteur ouvert maintient un VERROU :
        # la passe suivante ne pourrait plus ecrire dans ces journaux, et c est justement
        # sur une machine saturee qu on a le plus besoin de leurs traces. Fermer la copie
        # du parent est sans danger pour les enfants deja lances : ils ont la leur.
        try:
            proc = _sp.Popen([_sys.executable, "-c", code], stdout=fh, stderr=_sp.STDOUT,
                             start_new_session=True)
        except BaseException:
            for _journal in [fh] + [x[4] for x in lances]:
                try:
                    _journal.close()
                except OSError:
                    import logging as _lg
                    _lg.getLogger(__name__).debug(
                        "fermeture du journal impossible", exc_info=True)
            raise
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
            import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
            _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
        print("=== module %s ===" % strat, flush=True)
        try:
            print(log.read_text(encoding="utf-8"), end="", flush=True)   # sortie GROUPÉE, lisible
        except OSError:
            import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
            _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
        try:
            resultats[strat] = _json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            resultats[strat] = {"statut": "ERREUR", "strategie": strat,
                                "motif": "sous-processus sans resultat", "essais": []}
    return resultats


__all__ = ["remplir_en_parallele"]
