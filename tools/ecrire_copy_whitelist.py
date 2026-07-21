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


BRUTS_DEFAUT = Path("runtime") / "data" / "leader_fills_bruts.jsonl"


def construire_fills_forward(root: str | Path = RACINE, *, horizon_min: float = 30.0,
                             max_bruts: int = 60_000) -> int:
    """#185-SOURCE (21/07) — fabrique `leader_fills_forward.jsonl` en joignant :
      * les fills BRUTS du moteur (adresse/coin/side/ts — écrits par fusion_runtime) ;
      * les MARKS du replay (mid au fill : ≤5 min après le fill ; mid forward : premier mark
        ≥ ts+horizon, toléré jusqu'à horizon+15 min).
    Un fill sans mark exploitable est COMPTE PUIS IGNORÉ — jamais un mid inventé.
    Retourne le nombre de lignes écrites."""
    racine = Path(root)
    bruts_p = racine / BRUTS_DEFAUT
    if not bruts_p.exists():
        return 0
    from hl_observer.backtesting.ab_flag_replay import load_jsonl, marks_by_coin
    from hl_observer.backtesting.recherche_scenario import repertoire_replay_consolide
    base = repertoire_replay_consolide(racine)
    marks = marks_by_coin(load_jsonl(str(base / "marks.jsonl")))
    tries: dict[str, list] = {c: sorted((float(t), float(m)) for (t, m) in pts)
                              for c, pts in marks.items()}
    lignes = []
    bruts = [l for l in bruts_p.read_text(encoding="utf-8").splitlines() if l.strip()]
    for l in bruts[-max_bruts:]:
        try:
            f = json.loads(l)
            coin, ts = str(f.get("coin") or "").upper(), float(f.get("ts_ms") or 0) / 1000.0
        except (ValueError, TypeError):
            continue
        pts = tries.get(coin)
        if not pts or not f.get("adresse") or ts <= 0:
            continue
        mid_fill = next((m for (t, m) in pts if ts <= t <= ts + 300.0), None)
        h = horizon_min * 60.0
        mid_fwd = next((m for (t, m) in pts if ts + h <= t <= ts + h + 900.0), None)
        if mid_fill and mid_fwd:
            lignes.append(json.dumps({"adresse": f["adresse"], "side": f.get("side"),
                                      "mid_at_fill": mid_fill, "mid_forward": mid_fwd},
                                     ensure_ascii=False))
    sortie = racine / FILLS_DEFAUT
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text("\n".join(lignes) + ("\n" if lignes else ""), encoding="utf-8")
    return len(lignes)


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
            # 21/07 : la PROGRESSION vers la preuve, ecrite dans le fichier (pas seulement a
            # l'ecran) — « 0 garde » sans detail ressemble a une panne ; avec le detail, on
            # voit le copy revenir : qui est evalue, avec combien de fills, ce qui manque.
            "details": [{"adresse": v.adresse, "n_events": v.n_evenements,
                         "markout_moyen_bps": v.markout_moyen_bps, "motif": v.motif,
                         "predit": v.predit} for v in verdicts],
            "rejetes": sum(1 for v in verdicts if not v.predit),
            "regle": "markout forward > seuil sur assez d'events (C12) ; liste vide = copy "
                     "verrouille (deny-by-default) ; les portes actuelles restent AU-DESSUS",
            "real_execution": False}


def ecrire(root: str | Path = RACINE, **kw) -> Path:
    # #185-source : reconstruire les fills forward depuis les bruts du moteur AVANT la
    # selection — la chaine complete tourne a chaque passe du collecteur (6 h).
    try:
        n = construire_fills_forward(root)
        print("fills forward reconstruits : %d ligne(s) (bruts moteur x marks replay)" % n)
    except Exception as exc:  # noqa: BLE001 — la selection tombera sur liste vide, honnete
        print("fills forward indisponibles : %s" % exc)
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
    # 21/07 (Flo : « je veux que notre copytrading soit parfait ») : un « 0 garde » muet
    # ressemble a une panne. On DIT la progression : qui est evalue, avec combien de fills,
    # et ce qu'il manque pour trancher. Le copy revient par la preuve — autant la voir venir.
    det = d.get("details") or []
    if det:
        from hl_observer.copy_wallet.leader_markout import MIN_EVENEMENTS
        print("  progression vers la preuve (il faut >= %d fills mesures par leader) :"
              % MIN_EVENEMENTS)
        for v in det[:8]:
            print("    %-14s %3d fill(s) · markout %s · %s"
                  % (str(v.get("adresse"))[:14], v.get("n_events") or 0,
                     ("%+.2f bps" % v["markout_moyen_bps"])
                     if v.get("markout_moyen_bps") is not None else "non mesurable",
                     v.get("motif")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
