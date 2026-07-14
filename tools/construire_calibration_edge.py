#!/usr/bin/env python3
"""CONSTRUIT LA TABLE D'EDGE MESUREE (2026-07-11) -- a partir des VRAIS signaux enregistres.

Le bot refuse desormais tout edge qui n'a jamais touche un prix. Il lui faut donc une table
d'edge MESUREE, indexee par la fraicheur du signal.

Cette table n'est PAS un reglage. C'est un releve. Si le marche ne bouge pas apres un signal,
la table le dira, et le bot refusera -- ce qui est le comportement correct, pas une panne.

    python tools/construire_calibration_edge.py [dossier_replay]

LECTURE SEULE sur les donnees. Ecrit runtime/calibration/empirical_edge.json.
Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import bisect
import glob
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Bandes de fraicheur. L'age est la SEULE dimension dont on ait prouve qu'elle compte.
BANDES = [(0, 1_000), (1_000, 5_000), (5_000, 15_000), (15_000, 60_000), (60_000, 300_000)]
HORIZON_MESURE_MS = 30_000       # a quel horizon on evalue le mouvement (le plus echantillonne)
MIN_ECHANTILLON = 200            # en dessous : la bande est declaree NON MESUREE


def _ms(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x <= 0 else (x * 1000.0 if x < 1e11 else x)


def _lire(motif):
    out = []
    for f in sorted(glob.glob(str(ROOT / motif))):
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except OSError:
            pass
    return out


def main() -> int:
    dossier = sys.argv[1] if len(sys.argv) > 1 else "runtime/replay/_archive/run_20260709_152414"
    marks = _lire(f"{dossier}/marks*.jsonl")
    cands = _lire(f"{dossier}/candidates*.jsonl")
    print(f"\n  source : {dossier}")
    print(f"  {len(marks)} prix - {len(cands)} signaux")

    chemins = defaultdict(list)
    for m in marks:
        t, coin, mid = _ms(m.get("ts")), str(m.get("coin") or ""), m.get("mid")
        try:
            p = float(mid)
        except (TypeError, ValueError):
            continue
        if t and coin and p > 0:
            chemins[coin].append((t, p))
    for c in chemins:
        chemins[c].sort()

    # mouvement realise, dans le sens du leader, par bande de fraicheur
    par_bande = defaultdict(list)
    for c in cands:
        coin = str(c.get("coin") or "")
        side = str(c.get("direction") or c.get("side") or "").upper()
        t0 = _ms(c.get("recorded_at"))
        age = c.get("signal_age_ms")
        try:
            prix0 = float(c.get("current_mid") or 0.0)
            age = float(age)
        except (TypeError, ValueError):
            continue
        if not coin or side not in {"LONG", "SHORT"} or not t0 or prix0 <= 0 or coin not in chemins:
            continue

        serie = chemins[coin]
        i = bisect.bisect_left(serie, (t0 + HORIZON_MESURE_MS, float("-inf")))
        if i >= len(serie) or (serie[i][0] - t0) > HORIZON_MESURE_MS * 1.5:
            continue                       # pas de prix a cet horizon : on n'invente pas
        prix1 = serie[i][1]
        sens = 1.0 if side == "LONG" else -1.0
        bps = (prix1 - prix0) / prix0 * 10_000.0 * sens        # dans le sens du leader

        for amin, amax in BANDES:
            if amin <= age < amax:
                par_bande[(amin, amax)].append(bps)
                break

    bandes = []
    print(f"\n  {'bande de fraicheur':>22} {'n':>6} {'edge median':>13}  statut")
    print(f"  {'-'*22} {'-'*6} {'-'*13}  {'-'*22}")
    for amin, amax in BANDES:
        vals = par_bande.get((amin, amax), [])
        n = len(vals)
        lib = f"{amin/1000:.0f}-{amax/1000:.0f} s"
        if n < MIN_ECHANTILLON:
            print(f"  {lib:>22} {n:>6} {'--':>13}  NON MESUREE (refus)")
            continue                       # bande absente => le bot refusera : etat vide honnete
        med = statistics.median(vals)
        bandes.append({
            "age_min_ms": amin, "age_max_ms": amax,
            "edge_bps": round(med, 4), "sample_size": n,
            "horizon_ms": HORIZON_MESURE_MS,
        })
        print(f"  {lib:>22} {n:>6} {med:>+12.2f}b  MESUREE")

    table = {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": dossier,
        "horizon_ms": HORIZON_MESURE_MS,
        "min_sample_size": MIN_ECHANTILLON,
        "bands": bandes,
        "note": (
            "Releve, pas reglage. Un edge median proche de zero pour un cout de 13 bps signifie "
            "qu'il n'y a rien a copier -- le refus qui en decoule est CORRECT, pas une panne."
        ),
        "real_execution": False,
    }
    out = ROOT / "runtime" / "calibration" / "empirical_edge.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(table, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  ecrit : {out.relative_to(ROOT)}  ({len(bandes)} bande(s) mesuree(s))\n")
    return 0 if bandes else 2


if __name__ == "__main__":
    sys.exit(main())
