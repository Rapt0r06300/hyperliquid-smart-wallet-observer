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
    # ══ 🔴 21/07 — POURQUOI 97,6 % DES FILLS N'AVAIENT PAS DE PRIX ══
    # La whitelist etait vide : 12 leaders evalues, 0 qualifie, aucun n'atteignant les 30
    # mesures exigees. On croyait la porte trop stricte ; elle n'avait RIEN a juger.
    #     fills bruts 7 184  ->  fills avec markout 173  =  2,4 %
    # Instrumentation : 88,4 % perdus sur « pas de mark ». Puis la mesure decisive :
    #     marks lus : de -319,1 h a -10,9 h   (s'ARRETENT il y a 11 h)
    #     fills     : de  -11,8 h a  -0,2 h   (1 h de recouvrement)
    # Ni la fenetre ni la densite : sur BTC/HYPE/ETH les marks tombent toutes les 2 SECONDES.
    # Le pipeline lisait `_merged/marks.jsonl` fige a 10:06 pendant que les shards bruts
    # `marks.*.jsonl` continuaient d'etre ecrits jusqu'a 20:38. La collecte VIVAIT ; c'est la
    # CONSOLIDATION qui n'avait pas tourne depuis 11 heures.
    # `marks_source` lit donc le consolide ET les shards frais, prend le mark le plus proche
    # AVANT OU APRES (l'ancienne regle ne regardait qu'apres : un mark 30 s avant etait rejete
    # quand un mark 290 s apres passait), et SIGNALE un recouvrement rompu.
    from hl_observer.copy_wallet.marks_source import (apparier_avec_cause, charger_marks,
                                                      diagnostic_recouvrement)
    tries = charger_marks(racine)
    lignes = []
    causes: dict[str, int] = {}
    ts_fills: list[float] = []
    bruts = [l for l in bruts_p.read_text(encoding="utf-8").splitlines() if l.strip()]
    import time as _time
    _now = _time.time()
    ecartes = 0
    for l in bruts[-max_bruts:]:
        try:
            f = json.loads(l)
            coin, ts = str(f.get("coin") or "").upper(), float(f.get("ts_ms") or 0) / 1000.0
        except (ValueError, TypeError):
            continue
        # 🔴 21/07 — DES FIXTURES DE TEST DANS LA DONNEE LIVE. L'audit de fraicheur annoncait
        # 495 734 h d'etendue (56 ans) sur ce fichier : 3 lignes portaient ts_ms=0 et des
        # adresses 0x1111.../0x2222.../0x3333.... Un leader synthetique qui accumulerait assez
        # de fills pourrait entrer dans la whitelist — c'est-a-dire debloquer le copy sur une
        # donnee FABRIQUEE. Regle : un fill doit etre horodate dans une fenetre plausible et
        # porter une adresse qui n'est pas un motif de test.
        if not (1_577_836_800.0 <= ts <= _now + 3600.0):
            ecartes += 1
            continue
        _adr = str(f.get("adresse") or "").lower()
        if _adr[2:].strip("0123456789abcdef") == "" and len(set(_adr[2:])) <= 1:
            ecartes += 1          # 0x1111..., 0x0000... : motif synthetique, jamais un wallet
            continue
        if not f.get("adresse") or ts <= 0:
            continue
        ts_fills.append(ts)
        r = apparier_avec_cause(tries, coin=coin, ts=ts, horizon_s=horizon_min * 60.0)
        if not r.get("ok"):
            causes[r["cause"]] = causes.get(r["cause"], 0) + 1
            continue
        lignes.append(json.dumps(
            {"adresse": f["adresse"], "side": f.get("side"),
             "mid_at_fill": r["mid_at_fill"], "mid_forward": r["mid_forward"],
             # l'ECART temporel voyage avec la mesure : un appariement lointain doit rester
             # contestable plus tard, pas se fondre anonymement dans une moyenne.
             "ecart_fill_s": r["ecart_fill_s"], "ecart_forward_s": r["ecart_forward_s"],
             "coin": coin, "ts_ms": int(ts * 1000)}, ensure_ascii=False))
    if ecartes:
        print("  %d fill(s) ECARTE(S) : horodatage implausible ou adresse synthetique "
              "(fixtures de test dans la donnee live)" % ecartes)
    # ── LE CONTROLE QUI MANQUAIT ────────────────────────────────────────────────────────
    # Ce bug a vecu 11 heures parce que le pipeline rendait 173 lignes au lieu de 7 000 SANS
    # RIEN DIRE. Une mesure qui perd 97 % de sa matiere doit le declarer.
    diag = diagnostic_recouvrement(tries, ts_fills)
    total = max(1, len(ts_fills))
    print("  markout : %d mesure(s) sur %d fill(s) = %.1f %%"
          % (len(lignes), total, 100.0 * len(lignes) / total))
    if causes:
        print("  causes de perte : "
              + " · ".join("%s=%d" % (k, v)
                           for k, v in sorted(causes.items(), key=lambda kv: -kv[1])))
    if diag.get("rompu"):
        print("  !! RECOUVREMENT ROMPU : %s" % diag.get("motif"))
        print("     -> lance la consolidation du replay AVANT de juger un leader :")
        print("        python -m hl_observer.runtime.replay_recorder --base runtime/replay")
    sortie = racine / FILLS_DEFAUT
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text("\n".join(lignes) + ("\n" if lignes else ""), encoding="utf-8")
    # le diagnostic est ECRIT a cote : la whitelist doit pouvoir dire si son verdict repose
    # sur une mesure complete ou sur un pipeline en retard.
    try:
        (racine / FILLS_DEFAUT).with_suffix(".diagnostic.json").write_text(
            json.dumps({**diag, "mesures": len(lignes), "fills": total,
                        "couverture_pct": round(100.0 * len(lignes) / total, 2),
                        "causes": causes, "real_execution": False},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
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
