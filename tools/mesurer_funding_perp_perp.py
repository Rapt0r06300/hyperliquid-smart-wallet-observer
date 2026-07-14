"""#365 / X-04 / H-137 — MESURER le funding arb PERP↔PERP sur NOS données (2026-07-13).

115 768 relevés de funding, 232 coins, 18,9 h — avec `mark_px` à chaque relevé.
On peut donc calculer le beta ET le funding, sur les MEMES instants.

Sortie : data/reports/funding_perp_perp.json

Aucun ordre reel : lecture de fichiers, arithmetique.
"""
from __future__ import annotations

import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.funding.funding_spread_perp_perp import (  # noqa: E402
    MIN_POINTS,
    MOTIF_PAS_UNE_COUVERTURE,
    MOTIF_RESIDU_DOMINE,
    evaluer_paire,
)

PAS_S = 60.0
TOP = 16          # n² : 16 coins = 120 paires. Assez, et on garde le contrôle de multiplicité.


def charger():
    """{coin: {bucket: (mark_px, funding_bps_h)}} — apparié par le TEMPS, jamais ligne à ligne."""
    par_coin: dict[str, dict[int, tuple[float, float]]] = defaultdict(dict)
    for f in (RACINE / "runtime" / "replay").rglob("funding*.jsonl"):
        for ligne in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not ligne.strip():
                continue
            try:
                d = json.loads(ligne)
                coin = str(d.get("coin") or "")
                px = float(d.get("mark_px") or 0.0)
                fb = float(d.get("funding_bps_hourly") or 0.0)
                ts = float(d.get("ts") or 0.0)
            except (ValueError, TypeError):
                continue
            if not coin or px <= 0 or ts <= 0:
                continue
            par_coin[coin][int(ts // PAS_S)] = (px, fb)
    return par_coin


def main() -> int:
    print("=" * 96)
    print("  #365 / X-04 / H-137 -- FUNDING ARB **PERP <-> PERP**")
    print("  La zone morte FUNDING_JAMBE_NUE designe ELLE-MEME cette voie :")
    print("  « une VRAIE jambe de couverture (spot ou **perp oppose**) ».")
    print("=" * 96)

    data = charger()
    assez = {c: v for c, v in data.items() if len(v) >= MIN_POINTS}
    print("  %d coins, dont %d avec >= %d relevés apparies" % (len(data), len(assez), MIN_POINTS))
    if len(assez) < 2:
        print("\n  INSUFFICIENT_DATA. On ne conclut PAS.")
        return 0

    tops = sorted(assez, key=lambda c: len(assez[c]), reverse=True)[:TOP]
    print("  coins retenus : %s" % ", ".join(tops))
    print()

    verdicts = []
    for a, b in itertools.combinations(tops, 2):
        communs = sorted(set(assez[a]) & set(assez[b]))
        if len(communs) < MIN_POINTS:
            continue
        pa = [assez[a][k][0] for k in communs]
        pb = [assez[b][k][0] for k in communs]
        fa = sorted(assez[a][k][1] for k in communs)
        fb = sorted(assez[b][k][1] for k in communs)
        med_a = fa[len(fa) // 2]
        med_b = fb[len(fb) // 2]
        verdicts.append(evaluer_paire(a, b, pa, pb, med_a, med_b, pas_par_heure=3600.0 / PAS_S))

    verdicts.sort(key=lambda v: v.ratio, reverse=True)
    couvertures = [v for v in verdicts if v.motif != MOTIF_PAS_UNE_COUVERTURE
                   and v.motif != "INSUFFICIENT_DATA"]
    viables = [v for v in verdicts if v.viable]

    print("-" * 96)
    print("  paires evaluees                    : %d" % len(verdicts))
    print("  ... qui sont de VRAIES couvertures : %d  (R² >= 0,30)" % len(couvertures))
    print("  ... VIABLES apres residu + couts   : %d" % len(viables))
    print("-" * 96)
    print()
    print("  %-7s %-7s %-6s %-7s %-9s %-10s %-9s  %s" % (
        "A", "B", "R2", "beta", "ecart f.", "RESIDU/h", "ratio", "motif"))
    for v in verdicts[:20]:
        print("  %-7s %-7s %-6.3f %-7.2f %-9.3f %-10.1f %-9.4f  %s" % (
            v.a, v.b, v.r2, v.beta, v.ecart_funding_bps_h, v.residu_bps_h, v.ratio,
            v.motif[:30]))

    print()
    print("  ecart f. = ce qu'on ENCAISSE par heure (bps, delta-ajuste)")
    print("  RESIDU/h = ce que le prix SUBI bouge par heure APRES couverture (bps)")
    print("  ratio    = encaisse / subi. **C'est la seule colonne qui decide.**")
    print()

    if not viables:
        n_res = sum(1 for v in verdicts if v.motif == MOTIF_RESIDU_DOMINE)
        print("  ═══════════════════════════════════════════════════════════════════════════")
        print("  VERDICT : AUCUNE paire viable.")
        if n_res:
            print("  %d paires meurent du RESIDU : ce qui reste apres couverture bouge PLUS que" % n_res)
            print("  le funding encaisse. *C'est le meme piege que la jambe nue -- en payant")
            print("  deux fois plus de frais.*")
        print("  ═══════════════════════════════════════════════════════════════════════════")
    else:
        print("  ⚠️ %d paire(s) survivent sur %d testees. **NE PAS SUR-INTERPRETER** :"
              % (len(viables), len(verdicts)))
        print("     le hasard seul fait ressortir quelques paires sur 120. Controle de")
        print("     multiplicite EXIGE (le gate anti-overfit vient d'etre branche, #395).")
        print("     ⚠️ NON MODELISE : liquidation d'une jambe (T2b : /2), ADL, rupture de")
        print("     correlation. **Tous DEGRADENT** ces chiffres.")
        for v in viables:
            print("     %s/%s : %s" % (v.a, v.b, v.note))

    out = RACINE / "data" / "reports" / "funding_perp_perp.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "n_paires": len(verdicts),
        "n_couvertures": len(couvertures),
        "n_viables": len(viables),
        "coins": tops,
        "paires": [v.as_dict() for v in verdicts],
        "non_modelise": ["liquidation d'une jambe", "ADL", "rupture de correlation"],
        "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
