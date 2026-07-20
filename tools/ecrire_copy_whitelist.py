"""WHITELIST MARKOUT (#13, vague 1) — le copy ne suivra QUE les leaders qui PRÉDISENT.

LOI (11/07) : le copy GLOBAL n'a pas d'edge (−7,97 bps OOS, leader contrarien). Mais la loi
juge la MOYENNE — pas chaque wallet. C12/C13 (leader_markout) savent juger un leader sur son
markout forward RÉEL. Cet outil produit la whitelist hebdomadaire :

    runtime/data/copy_whitelist.json = les adresses au markout > seuil sur assez d'events.

PLAN DE CÂBLAGE (assumé, engine côté Windows — tâche dédiée) : la porte copy du moteur lira
ce fichier et refusera tout leader hors liste (deny-by-default : fichier absent = liste vide
= copy toujours verrouillé, comme aujourd'hui). Ce fichier ne DÉVERROUILLE rien tout seul :
les portes actuelles (edge 16 bps, consensus 2) restent au-dessus.

Entrée : un JSONL de fills forward-marqués {adresse, side, mid_at_fill, mid_forward}
(produit par le pipeline markout C12). Lecture seule, aucun ordre.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_wallet.leader_markout import selectionner_leaders  # noqa: E402

FILLS_DEFAUT = Path("runtime") / "data" / "leader_fills_forward.jsonl"
SORTIE = Path("runtime") / "data" / "copy_whitelist.json"


def construire_whitelist(root: str | Path = RACINE, *, fills_path: str | Path | None = None,
                         fills: list | None = None) -> dict:
    """{gardes: [{adresse, markout_moyen_bps, n}], rejetes: n, regle}. Vide si pas de donnees
    (deny-by-default : une whitelist vide verrouille, elle n'invente pas)."""
    racine = Path(root)
    lignes = fills
    if lignes is None:
        chemin = Path(fills_path) if fills_path else racine / FILLS_DEFAUT
        lignes = []
        try:
            for l in chemin.read_text(encoding="utf-8", errors="ignore").splitlines():
                l = l.strip()
                if l:
                    try:
                        r = json.loads(l)
                        if isinstance(r, dict):
                            lignes.append(r)
                    except ValueError:
                        continue
        except OSError:
            lignes = []
    par_leader: dict[str, list] = defaultdict(list)
    for f in lignes:
        a = str(f.get("adresse") or f.get("wallet") or "").strip()
        if a:
            par_leader[a].append(f)
    verdicts = selectionner_leaders(par_leader)
    gardes = [{"adresse": v.adresse, "markout_moyen_bps": v.markout_moyen_bps,
               "n_evenements": v.n_evenements} for v in verdicts if v.predit]
    return {"genere_ts": time.time(), "gardes": gardes,
            "rejetes": sum(1 for v in verdicts if not v.predit),
            "regle": "markout forward > seuil sur assez d'events (C12) ; liste vide = copy "
                     "verrouille (deny-by-default) ; les portes actuelles restent AU-DESSUS",
            "real_execution": False}


def ecrire(root: str | Path = RACINE, **kw) -> Path:
    r = construire_whitelist(root, **kw)
    chemin = Path(root) / SORTIE
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return chemin


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description="Whitelist markout des leaders (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--fills", default=None)
    a = p.parse_args(argv)
    chemin = ecrire(a.root, fills_path=a.fills)
    d = json.loads(chemin.read_text(encoding="utf-8"))
    print("whitelist ecrite : %s — %d garde(s), %d rejete(s)"
          % (chemin, len(d["gardes"]), d["rejetes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
