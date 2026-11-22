r"""Apprentissage PARALLÈLE du bac à sable : toutes les variantes jugées en même temps, sur données neuves.

POURQUOI. La boucle séquentielle essayait UNE variante à la fois et attendait 20 cycles pour chacune :
15 variantes = 300 cycles successifs, des semaines. Et le bac à sable n'ouvre jamais sans avance
mesurée (garde voulue) : il n'y avait donc jamais de cycle à juger. Ici, chaque fill de leader assez
ancien pour être résolu par TOUTES les variantes est simulé une fois pour les 45 variantes que le
moteur sait exécuter (5 seuils × 3 stops × 3 horizons, sortie miroir comme `LEADER_A_CLOS`), et son
résultat est inscrit pour chacune. Un même flux neuf nourrit toutes les comparaisons.

DÉCIDER SANS SE MENTIR :
* **données neuves seulement** : seuls les fills reçus après le premier passage (`debut_ms`) comptent ;
* **aucune sélection sur l'issue** : un fill n'est inscrit que lorsqu'il est assez vieux pour être
  résolu par l'horizon le plus long, quel que soit son résultat (voir `cycles_fantomes`) ;
* **dépendance entre cycles** : l'intervalle est un bootstrap par BLOCS de jours ;
* **essais multiples ET regards répétés** : le niveau est corrigé par le nombre de variantes encore
  en lice × le nombre de jours déjà regardés (Bonferroni, conservateur) ;
* **élimination successive** : une variante dont la borne HAUTE est sous la meilleure borne BASSE est
  écartée pour de bon ;
* **championne** : borne basse > 0, au moins `JOURS_MIN` jours et `CYCLES_MIN` cycles.

ET APRÈS. Seule une championne transmet au bac à sable une avance MESURÉE (sa borne basse, ajoutée au
coût fantôme) : le moteur ouvre alors en papier réel, ses cycles réels sont jugés par la boucle
séquentielle, puis l'échelle PROBE → ALPHA s'applique. Sans championne, le bac à sable reste en
observation : on n'invente pas d'avance. PAPER ; aucun ordre ; aucun réseau.
"""
from __future__ import annotations

import json
import os
import random
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.experimental import cycles_fantomes as CF

FRACS = (0.0005, 0.001, 0.002, 0.004, 0.008)
STOPS = (20.0, 40.0, 80.0)
HORIZONS = (900_000.0, 3_600_000.0, 14_400_000.0)
HORIZON_MAX = max(HORIZONS)
JOURS_MIN = 5
CYCLES_MIN = 50
NIVEAU = 0.95
TIRAGES = 3000
GRAINE = 20_261_122
DOSSIER = Path("runtime") / "auto_amelioration"
REGISTRE = DOSSIER / "parallele_fills.ndjson"
ETAT = DOSSIER / "parallele_etat.json"
JOUR_MS = 86_400_000

Variante = tuple[float, float, float]


def grille() -> list[Variante]:
    return [(f, s, h) for f in FRACS for s in STOPS for h in HORIZONS]


def etiquette(v: Variante) -> str:
    return "par-f%r-s%r-h%r" % (float(v[0]), float(v[1]), float(v[2]))


def _lire_json(chemin: Path) -> dict:
    try:
        d = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _ecrire_atomique(chemin: Path, contenu: Any) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(f"{chemin.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(contenu, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, chemin)


def lire_registre(root: Path) -> list[dict]:
    try:
        texte = (Path(root) / REGISTRE).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    out, vus = [], set()
    for ligne in texte.splitlines():
        try:
            x = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(x, dict) and isinstance(x.get("res"), dict):
            if x.get("identite") in vus:
                continue                    # deux écrivains (moteur + processus autonome) : un fill compte UNE fois
            vus.add(x.get("identite"))
            out.append(x)
    return out


def simuler_les_fills(lignes, tape, tvl, *, debut_ms: float, now_ms: float, notional_usd: float = 20.0,
                      deja: set[str] | None = None) -> tuple[list[dict], dict]:
    """Un enregistrement par fill RÉSOLU pour toutes les variantes : {identite, jour, res: {etiquette: usd|None}}.

    `res[v]` vaut None quand la variante v n'aurait pas déclenché (seuil plus haut) ou n'a pas de prix :
    c'est une ABSENCE de cycle pour v, pas un zéro."""
    deja = deja or set()
    par_fill: dict[str, dict] = {}
    comptes: dict[str, int] = {}
    for v in grille():
        # chaque variante ne résout que les fills assez vieux pour l'horizon le PLUS LONG : tous les fills
        # inscrits le sont donc pour toutes les variantes à la fois (aucune ne voit un futur que l'autre n'a pas)
        sim = CF.simuler(lignes, tape, tvl, frac_tvl=v[0], stop_bps=v[1], horizon_ms=v[2], depuis_ms=debut_ms,
                         now_ms=now_ms - (HORIZON_MAX - v[2]), notional_usd=notional_usd, etiquette=etiquette(v))
        for k, n in sim["compte"].items():
            comptes[k] = comptes.get(k, 0) + n
        for c in sim["cycles"]:
            rec = par_fill.setdefault(c["identite"], {"identite": c["identite"], "jour": int(c["entree_ms"] // JOUR_MS),
                                                      "coin": c["coin"], "vault": c["vault"], "res": {},
                                                      "contexte": c.get("contexte")})
            rec["res"][etiquette(v)] = c["realized_usd"]
    neufs = []
    for ident, rec in par_fill.items():
        if ident in deja:
            continue
        for v in grille():                                   # absence explicite pour les variantes muettes
            rec["res"].setdefault(etiquette(v), None)
        neufs.append(rec)
    return neufs, comptes


def _bootstrap_jours(par_jour: Mapping[int, list[float]], *, alpha: float, graine: int = GRAINE) -> tuple[float, float, float]:
    jours = [j for j, v in par_jour.items() if v]
    if not jours:
        return float("nan"), float("nan"), float("nan")
    sommes = {j: sum(par_jour[j]) for j in jours}
    nombres = {j: len(par_jour[j]) for j in jours}
    moyenne = sum(sommes.values()) / sum(nombres.values())
    if len(jours) < 2:
        return moyenne, float("nan"), float("nan")
    rng = random.Random(graine)
    tires = []
    for _ in range(TIRAGES):
        ech = [rng.choice(jours) for _ in jours]
        tires.append(sum(sommes[j] for j in ech) / max(1, sum(nombres[j] for j in ech)))
    tires.sort()
    bas = tires[max(0, int((alpha / 2) * (TIRAGES - 1)))]
    haut = tires[min(TIRAGES - 1, int((1 - alpha / 2) * (TIRAGES - 1)))]
    return moyenne, bas, haut


def juger(registre: Sequence[Mapping[str, Any]], *, eliminees: set[str]) -> dict:
    """Bornes de chaque variante en lice, élimination successive, championne éventuelle."""
    par_v: dict[str, dict[int, list[float]]] = {}
    for r in registre:
        for lab, usd in (r.get("res") or {}).items():
            if usd is None or lab in eliminees:
                continue
            par_v.setdefault(lab, {}).setdefault(int(r["jour"]), []).append(float(usd))
    en_lice = [etiquette(v) for v in grille() if etiquette(v) not in eliminees]
    jours_vus = len({int(r["jour"]) for r in registre})
    alpha = (1.0 - NIVEAU) / max(1, len(en_lice) * max(1, jours_vus))
    bornes = {}
    for lab in en_lice:
        pj = par_v.get(lab, {})
        m, b, h = _bootstrap_jours(pj, alpha=alpha)
        bornes[lab] = {"moyenne_usd": m, "bas": b, "haut": h, "cycles": sum(len(x) for x in pj.values()), "jours": len(pj)}
    valides = {k: x for k, x in bornes.items() if x["bas"] == x["bas"]}          # bornes calculables (pas NaN)
    meilleure_basse = max((x["bas"] for x in valides.values()), default=float("nan"))
    nouvelles = [k for k, x in valides.items() if x["haut"] < meilleure_basse]
    championne = None
    for k, x in sorted(valides.items(), key=lambda kv: -kv[1]["bas"]):
        if x["bas"] > 0 and x["jours"] >= JOURS_MIN and x["cycles"] >= CYCLES_MIN:
            championne = k
            break
    return {"alpha": alpha, "en_lice": len(en_lice), "jours_vus": jours_vus, "bornes": bornes,
            "a_eliminer": sorted(nouvelles), "championne": championne}


def sans_nan(x: Any) -> Any:
    """NaN et infinis -> None (« inconnu »). JSON ne connaît pas NaN : un navigateur refuse la page entière."""
    if isinstance(x, float):
        return x if x == x and x not in (float("inf"), float("-inf")) else None
    if isinstance(x, dict):
        return {k: sans_nan(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [sans_nan(v) for v in x]
    return x


def lire_variante(lab: str) -> Variante | None:
    try:
        f, s, h = lab[len("par-f"):].split("-s")[0], lab.split("-s")[1].split("-h")[0], lab.split("-h")[1]
        return float(f), float(s), float(h)
    except (IndexError, ValueError):
        return None


def une_passe(root: Path, *, ecrire: bool, now_ms: int | None = None, tape: Mapping | None = None,
              notional_usd: float = 20.0, cout_bps: float = CF.COUT_BPS) -> dict:
    """Inscrit les fills neufs, juge, élimine, et rend la décision. N'écrit que si `ecrire`."""
    root = Path(root)
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    etat = _lire_json(root / ETAT)
    debut = float(etat.get("debut_ms") or now_ms)
    eliminees = set(etat.get("eliminees") or [])
    registre = lire_registre(root)
    if tape is None:
        # seule la fenêtre utile : un fill se résout au plus HORIZON_MAX + marge après son entrée
        fenetre = max(debut, now_ms - HORIZON_MAX - CF.MARGE_RESOLUTION_MS - 1_800_000)
        tape = CF.bande_de_prix(root, depuis_ms=fenetre)
    neufs, comptes = simuler_les_fills(CF.lire_journal(root), tape, CF.tvl_par_vault(root), debut_ms=debut,
                                       now_ms=now_ms, notional_usd=notional_usd,
                                       deja={r["identite"] for r in registre})
    tous = registre + neufs
    verdict = juger(tous, eliminees=eliminees)
    decision: dict[str, Any] = {"action": "OBSERVER", "motif": "aucune variante ne prouve une avance positive"}
    if verdict["championne"]:
        v = lire_variante(verdict["championne"])
        b = verdict["bornes"][verdict["championne"]]
        lcb_bps = 1e4 * b["bas"] / notional_usd
        decision = {"action": "ARMER", "variante": verdict["championne"], "frac_tvl": v[0], "stop_bps": v[1],
                    "horizon_ms": v[2], "edge_brut_bps": round(lcb_bps + cout_bps, 4),
                    "motif": "borne basse corrigee %.2f bps net sur %d cycles / %d jours" % (lcb_bps, b["cycles"], b["jours"])}
    nouvel_etat = {"schema": "alina.apprentissage_parallele.v1", "debut_ms": debut, "maj_ms": now_ms,
                   "eliminees": sorted(eliminees | set(verdict["a_eliminer"])), "fills_inscrits": len(tous),
                   "fills_ce_passage": len(neufs), "comptes_ce_passage": comptes,
                   "verdict": {k: v for k, v in verdict.items() if k != "bornes"},
                   "meilleures": dict(sorted(verdict["bornes"].items(), key=lambda kv: -(kv[1]["bas"] if kv[1]["bas"] == kv[1]["bas"] else -1e9))[:5]),
                   "decision": decision, "paper": True, "real_execution": False}
    if ecrire:
        if neufs:
            chemin = root / REGISTRE
            chemin.parent.mkdir(parents=True, exist_ok=True)
            with chemin.open("a", encoding="utf-8") as f:
                for r in neufs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        _ecrire_atomique(root / ETAT, sans_nan(nouvel_etat))
    return sans_nan(nouvel_etat)


__all__ = ["CYCLES_MIN", "JOURS_MIN", "etiquette", "grille", "juger", "lire_registre", "lire_variante",
           "simuler_les_fills", "une_passe"]
