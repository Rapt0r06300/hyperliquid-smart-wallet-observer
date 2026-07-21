"""QUALITÉ DES DONNÉES DE REPLAY (21/07, Flo : « les données doivent être d'ultra bonne
qualité pour que le replay trouve la meilleure stratégie »).

Un replay ne vaut JAMAIS mieux que ses données. Ce module les AUSCULTE et écrit un verdict
par défaut connu — chacun a tué une mesure de ce projet au moins une fois :

  1. ÉTIQUETAGE     : un candidat sans `strategie` part dans le mauvais seau (les '?'
     historiques = copy) -> les modules se contaminent.
  2. HORODATAGE     : sans `recorded_at`, pas de coupe temporelle -> pas d'anti-lookahead.
  3. COUVERTURE     : un candidat dont le coin n'a AUCUN mark après lui est INMESURABLE
     (l'outcome n'existe pas) — c'est la cause n°1 des « 0 trade » du replay.
  4. RÉSOLUTION     : des marks trop espacés donnent des sorties SL/TP fantaisistes.
  5. DOUBLONS       : la même ligne comptée deux fois gonfle artificiellement un net.
  6. PRIX ABSURDES  : mid <= 0 ou variation > 50 % entre deux marks consécutifs.

Sortie : dict + `runtime/replay/QUALITE_DONNEES.md`. Lecture seule, aucun ordre.
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

#: barres de qualité — écrites AVANT la mesure (les déplacer se voit dans un diff)
COUVERTURE_MIN_PCT = 80.0        # % de candidats dont le coin a un mark APRÈS eux
RESOLUTION_MAX_MIN = 5.0         # espacement médian des marks des coins les plus suivis
ETIQUETAGE_MIN_PCT = 95.0
DOUBLONS_MAX_PCT = 1.0
SAUT_PRIX_ABSURDE = 0.5          # 50 % entre deux marks consécutifs = donnée à jeter


def _lire(chemin: Path, max_lignes: int = 400_000) -> list[dict]:
    out: list[dict] = []
    try:
        with chemin.open(encoding="utf-8") as fh:
            for i, l in enumerate(fh):
                if i >= max_lignes:
                    break
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    out.append(r)
    except OSError:
        return []
    return out


def auditer(root: str | Path = ".", *, max_lignes: int = 400_000) -> dict[str, Any]:
    from hl_observer.backtesting.recherche_scenario import repertoire_replay_consolide
    base = repertoire_replay_consolide(Path(root))
    cands = _lire(base / "candidates.jsonl", max_lignes)
    marks = _lire(base / "marks.jsonl", max_lignes)
    rap: dict[str, Any] = {"n_candidats": len(cands), "n_marks": len(marks),
                           "source": str(base), "defauts": [], "ts": time.time()}
    if not cands:
        rap["defauts"].append("AUCUN CANDIDAT consolidé — lancer la consolidation")
        return rap

    # 1. étiquetage + 2. horodatage
    strat = Counter(str(c.get("strategie") or "?") for c in cands)
    rap["par_strategie"] = dict(strat)
    etiquetes = 100.0 * (len(cands) - strat.get("?", 0)) / len(cands)
    rap["etiquetage_pct"] = round(etiquetes, 2)
    if etiquetes < ETIQUETAGE_MIN_PCT:
        rap["defauts"].append(
            "ÉTIQUETAGE : %.1f%% des candidats portent une `strategie` (barre %.0f%%) — les "
            "'?' sont traités comme copy ; un module mal étiqueté cherche dans le mauvais seau"
            % (etiquetes, ETIQUETAGE_MIN_PCT))
    sans_ts = sum(1 for c in cands if not float(c.get("recorded_at") or 0))
    rap["horodatage_pct"] = round(100.0 * (len(cands) - sans_ts) / len(cands), 2)
    if sans_ts:
        rap["defauts"].append("HORODATAGE : %d candidats sans `recorded_at` — invisibles pour "
                              "la coupe temporelle (anti-lookahead)" % sans_ts)

    # 3. couverture : un outcome existe-t-il ?
    marks_par_coin: dict[str, list[float]] = defaultdict(list)
    prix_par_coin: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for m in marks:
        c = str(m.get("coin") or "").upper()
        t = float(m.get("ts") or m.get("recorded_at") or 0.0)
        px = m.get("mid") or m.get("px") or m.get("mark")
        if c and t > 0:
            marks_par_coin[c].append(t)
            if isinstance(px, (int, float)) and px:
                prix_par_coin[c].append((t, float(px)))
    for c in marks_par_coin:
        marks_par_coin[c].sort()
    couverts = 0
    for cd in cands:
        c = str(cd.get("coin") or "").upper()
        t = float(cd.get("recorded_at") or 0.0)
        série = marks_par_coin.get(c)
        if série and t > 0 and série[-1] > t:
            couverts += 1
    rap["couverture_pct"] = round(100.0 * couverts / len(cands), 2)
    if rap["couverture_pct"] < COUVERTURE_MIN_PCT:
        rap["defauts"].append(
            "COUVERTURE : seuls %.1f%% des candidats ont un mark APRÈS eux (barre %.0f%%) — "
            "les autres sont INMESURABLES : c'est la cause n°1 des « 0 trade »"
            % (rap["couverture_pct"], COUVERTURE_MIN_PCT))

    # 4. résolution (top coins) + 6. prix absurdes
    reso = []
    for c, ts in sorted(marks_par_coin.items(), key=lambda kv: -len(kv[1]))[:10]:
        if len(ts) > 2:
            ecarts = sorted(b - a for a, b in zip(ts, ts[1:]))
            reso.append((c, ecarts[len(ecarts) // 2] / 60.0))
    rap["resolution_min"] = {c: round(m, 2) for c, m in reso}
    pires = [(c, m) for c, m in reso if m > RESOLUTION_MAX_MIN]
    if pires:
        rap["defauts"].append(
            "RÉSOLUTION : %s ont un mark toutes les >%.0f min — les sorties SL/TP simulées y "
            "sont grossières" % (", ".join(c for c, _ in pires[:5]), RESOLUTION_MAX_MIN))
    # 21/07 — enquête sur les 52 « sauts » du premier audit : TOUS sur des tickers TECHNIQUES
    # (`@128`, `#5101` = paires spot / indices internes HL, jamais nos coins) ou entre deux
    # marks séparés de 7 JOURS (664 397 s) — le prix a le droit de bouger en une semaine.
    # Un saut n'est suspect que s'il est RAPIDE (<10 min) et sur un VRAI coin.
    absurdes, suspects = 0, []
    for c, série in prix_par_coin.items():
        if not c or c[0] in "@#":                     # ticker technique : hors périmètre
            continue
        série.sort()
        for (t0, p0), (t1, p1) in zip(série, série[1:]):
            if p0 > 0 and (t1 - t0) <= 600.0 and abs(p1 - p0) / p0 > SAUT_PRIX_ABSURDE:
                absurdes += 1
                if len(suspects) < 5:
                    suspects.append("%s %.6g->%.6g en %.0fs" % (c, p0, p1, t1 - t0))
    rap["sauts_prix_absurdes"] = absurdes
    rap["sauts_exemples"] = suspects
    if absurdes:
        rap["defauts"].append("PRIX : %d sauts > %.0f%% en moins de 10 min sur de VRAIS coins "
                              "(%s) — vérifier la source"
                              % (absurdes, SAUT_PRIX_ABSURDE * 100, "; ".join(suspects)))

    # 5. doublons
    vus, doublons = set(), 0
    for cd in cands:
        cle = (cd.get("coin"), cd.get("recorded_at"), cd.get("direction"),
               cd.get("strategie"))
        if cle in vus:
            doublons += 1
        vus.add(cle)
    rap["doublons_pct"] = round(100.0 * doublons / len(cands), 3)
    if rap["doublons_pct"] > DOUBLONS_MAX_PCT:
        rap["defauts"].append("DOUBLONS : %.2f%% de candidats identiques — un net gonflé "
                              "artificiellement" % rap["doublons_pct"])

    rap["verdict"] = "PRÊT POUR LE REPLAY" if not rap["defauts"] else "DÉFAUTS À CORRIGER"
    return rap


def ecrire_rapport(root: str | Path = ".", rapport: dict | None = None) -> Path:
    r = rapport if rapport is not None else auditer(root)
    lignes = ["# QUALITÉ DES DONNÉES DE REPLAY", "",
              "_Un replay ne vaut jamais mieux que ses données. Barres écrites AVANT la "
              "mesure._", "",
              "- candidats : **%d** · marks : **%d**" % (r.get("n_candidats", 0),
                                                         r.get("n_marks", 0)),
              "- étiquetage : %s%% · horodatage : %s%% · couverture : %s%% · doublons : %s%%"
              % (r.get("etiquetage_pct"), r.get("horodatage_pct"),
                 r.get("couverture_pct"), r.get("doublons_pct")),
              "- par stratégie : `%s`" % r.get("par_strategie"),
              "- résolution des marks (min entre 2 marks) : `%s`" % r.get("resolution_min"),
              ""]
    if r.get("defauts"):
        lignes.append("## Défauts détectés")
        lignes.append("")
        lignes += ["- %s" % d for d in r["defauts"]]
    else:
        lignes.append("## Aucun défaut — les données sont prêtes")
    lignes += ["", "**VERDICT : %s**" % r.get("verdict", "?"), ""]
    p = Path(root) / "runtime" / "replay" / "QUALITE_DONNEES.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lignes), encoding="utf-8")
    import os
    os.replace(tmp, p)
    return p


def main(argv: list[str] | None = None) -> int:
    import sys
    root = (argv or sys.argv[1:] or ["."])[0]
    r = auditer(root)
    print(json.dumps({k: v for k, v in r.items() if k != "par_strategie"},
                     ensure_ascii=False, indent=1))
    print("\nrapport : %s" % ecrire_rapport(root, r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
