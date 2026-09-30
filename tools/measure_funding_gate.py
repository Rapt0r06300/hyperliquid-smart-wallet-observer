#!/usr/bin/env python3
"""LE SEUIL D'ENTRÉE DU GRINDER EST-IL ATTEIGNABLE ? — mesure, pas supposition.

CONTEXTE (2026-07-11). Le Grinder n'a fait **aucun trade**. Sa seule stratégie réellement câblée
est le funding-arb delta-neutre (`funding_arb_paper.py`). Son verrou d'entrée est :

    min_entry_edge_bps_per_hour = 2.5     # commentaire du code : "~20 bps/8h (repo 32 : minEdge 20)"

Le repo d'origine visait une place où le funding tombe **toutes les 8 heures**. Hyperliquid paie le
funding **toutes les heures**. Convertir « 20 bps par période » en « 2,5 bps par heure » est juste
*si et seulement si* le taux lu est lui aussi ramené à l'heure — ce qui est le cas ici
(`_hourly_rate_bps` = dernier taux × 10 000). La question n'est donc pas l'arithmétique, c'est :

    **2,5 bps/heure, est-ce un seuil que le marché franchit parfois, ou jamais ?**

Si le marché ne le franchit jamais, c'est un VERROU MORT — la même famille de bug que le plafond de
dégradation à 12 bps posé sous un coût plancher de 14,2 bps : 0 trade garanti, par construction.

JE NE PEUX PAS RÉPONDRE SANS LA DONNÉE. Cet outil va la chercher — sur ta machine, qui a le réseau.

    python tools/measure_funding_gate.py                 # instantané (tous les marchés)
    python tools/measure_funding_gate.py --seuil 2.5     # tester un autre seuil

LECTURE SEULE. Endpoint public `/info` uniquement. Aucun ordre, aucune clé, aucune signature.
Un instantané ne prouve rien à lui seul : le funding varie. Pour trancher, laisser tourner le
recorder (`HYPERSMART_RECORD_MICROSTRUCTURE=1`) et relire l'historique.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

HL_INFO = "https://api.hyperliquid.xyz/info"


def gate_report(rows: list[tuple[str, float]], seuil_bps_h: float) -> dict:
    """PUR et TESTABLE. `rows` = [(coin, taux_horaire_decimal), ...] tel que renvoyé par l'API.

    Le funding-arb encaisse le taux quand il est du bon côté : c'est |taux| qui compte, pas son
    signe (on prend la jambe qui reçoit). On rapporte donc la distribution de |taux| en bps/heure.
    """
    bps = sorted((abs(float(r)) * 10_000.0, str(c)) for c, r in rows)
    n = len(bps)
    if n == 0:
        return {"marches": 0, "verdict": "AUCUNE_DONNEE"}

    vals = [b for b, _ in bps]
    passent = [(b, c) for b, c in bps if b >= seuil_bps_h]

    def q(p: float) -> float:
        return round(vals[min(n - 1, int(p * n))], 4)

    part = len(passent) / n
    if part == 0.0:
        verdict = "VERROU_MORT — aucun marché ne franchit le seuil : 0 trade garanti"
    elif part < 0.02:
        verdict = "QUASI-MORT — moins de 2 % des marchés franchissent le seuil"
    elif part < 0.15:
        verdict = "SELECTIF — le seuil laisse passer une minorité de marchés"
    else:
        verdict = "PASSANT — le seuil n'est pas le facteur limitant"

    return {
        "marches": n,
        "seuil_bps_par_heure": seuil_bps_h,
        "mediane_bps_par_heure": q(0.50),
        "p90_bps_par_heure": q(0.90),
        "p99_bps_par_heure": q(0.99),
        "max_bps_par_heure": round(vals[-1], 4),
        "marches_au_dessus_du_seuil": len(passent),
        "part_au_dessus_du_seuil": round(part, 4),
        "exemples_au_dessus": [c for _, c in sorted(passent, reverse=True)[:10]],
        "verdict": verdict,
    }


def fetch_funding_rows() -> list[tuple[str, float]]:
    """Endpoint PUBLIC, lecture seule. Aucune donnée privée, aucun ordre."""
    req = urllib.request.Request(
        HL_INFO,
        data=json.dumps({"type": "metaAndAssetCtxs"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        meta, ctxs = json.loads(resp.read())
    rows: list[tuple[str, float]] = []
    for asset, ctx in zip(meta.get("universe") or [], ctxs or []):
        name = str(asset.get("name") or "")
        raw = ctx.get("funding")
        if not name or raw is None:
            continue
        try:
            rows.append((name, float(raw)))
        except (TypeError, ValueError):
            continue          # donnée illisible : on ne l'invente pas, on la saute
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seuil", type=float, default=2.5,
                    help="seuil d'entrée du funding-arb, en bps par heure (défaut : celui du code)")
    args = ap.parse_args()

    try:
        rows = fetch_funding_rows()
    except Exception as exc:                                   # pas de réseau -> état vide honnête
        print(f"  PAS D'ACCÈS À L'API PUBLIQUE : {type(exc).__name__}: {exc}")
        print("  Aucune mesure possible. Je ne devine pas de chiffre.")
        return 2

    rep = gate_report(rows, args.seuil)
    print(f"\n  FUNDING HYPERLIQUID — instantané réel, {rep['marches']} marchés")
    print(f"    médiane |funding|  : {rep['mediane_bps_par_heure']:>8.4f} bps/heure")
    print(f"    90e centile        : {rep['p90_bps_par_heure']:>8.4f} bps/heure")
    print(f"    99e centile        : {rep['p99_bps_par_heure']:>8.4f} bps/heure")
    print(f"    maximum            : {rep['max_bps_par_heure']:>8.4f} bps/heure")
    print(f"\n    SEUIL DU BOT       : {rep['seuil_bps_par_heure']:>8.4f} bps/heure")
    print(f"    marchés qui passent : {rep['marches_au_dessus_du_seuil']} / {rep['marches']} "
          f"({rep['part_au_dessus_du_seuil'] * 100:.1f} %)")
    if rep["exemples_au_dessus"]:
        print(f"    exemples            : {', '.join(rep['exemples_au_dessus'])}")
    print(f"\n    VERDICT : {rep['verdict']}\n")
    print("  ⚠  Un instantané ne prouve rien seul — le funding varie dans le temps.")
    print("     Pour trancher : HYPERSMART_RECORD_MICROSTRUCTURE=1 puis relire l'historique.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
