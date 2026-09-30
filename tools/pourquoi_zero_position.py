#!/usr/bin/env python3
"""POURQUOI LE BOT N'OUVRE RIEN -- la reponse, avec les chiffres (2026-07-11).

Un bot qui refuse tout ressemble a un bot casse. Ce script fait la difference entre les deux.

    python tools/pourquoi_zero_position.py

LECTURE SEULE. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.edge.empirical_edge import (  # noqa: E402
    ENV_REQUIRE_EMPIRICAL,
    edge_from_calibration,
    load_calibration,
)
from hl_observer.strategies.engine_economics import cout_aller_retour_bps  # noqa: E402


def main() -> int:
    print("\n" + "=" * 78)
    print("  POURQUOI LE BOT N'OUVRE AUCUNE POSITION ?")
    print("=" * 78)

    strict = str(os.environ.get(ENV_REQUIRE_EMPIRICAL, "1")).strip().lower() in {"1", "true", "on", "yes"}
    table = load_calibration()
    cout = cout_aller_retour_bps(spread_bps=2.0, slippage_bps=2.0)

    print(f"\n  Verrou d'edge empirique : {'ACTIF' if strict else 'DESACTIVE (mode A/B)'}")
    print(f"  Cout aller-retour reel  : {cout:.1f} bps (taker Hyperliquid 4,5 bps x2 + spread + slippage)")

    if not table or not table.get("bands"):
        print("\n  >>> AUCUNE TABLE D'EDGE MESUREE.")
        print("      Le bot refuse tout, non pas parce que l'edge est mauvais, mais parce qu'il")
        print("      ne le CONNAIT PAS. Construis-la :")
        print("          python tools/construire_calibration_edge.py")
        print()
        return 2

    print(f"  Table mesuree le        : {table.get('measured_at', '?')}")
    print(f"  Source                  : {table.get('source', '?')}\n")

    print(f"  {'fraicheur du signal':>22} {'n':>7} {'edge MESURE':>13} {'apres couts':>13}   verdict")
    print(f"  {'-'*22} {'-'*7} {'-'*13} {'-'*13}   {'-'*24}")

    un_seul_positif = False
    for b in table["bands"]:
        amin, amax = float(b["age_min_ms"]), float(b["age_max_ms"])
        edge, n = float(b["edge_bps"]), int(b["sample_size"])
        net = edge - cout
        lib = f"{amin/1000:.0f}-{amax/1000:.0f} s"
        verdict = "OUVRIRAIT" if net > 0 else "refuse (edge < couts)"
        if net > 0:
            un_seul_positif = True
        print(f"  {lib:>22} {n:>7} {edge:>+12.2f}b {net:>+12.2f}b   {verdict}")

    print()
    if un_seul_positif:
        print("  >>> Au moins une bande est rentable. Si le bot n'ouvre toujours rien, la cause")
        print("      est AILLEURS (liquidite, exposition, caps, fraicheur). Regarde les refus.")
        return 0

    print("  " + "-" * 74)
    print("  >>> LE BOT N'EST PAS CASSE. IL A RAISON.")
    print("  " + "-" * 74)
    print()
    print("  Toutes les bandes de fraicheur mesurees donnent un edge NEGATIF. Apres un ordre de")
    print("  whale, le prix ne va nulle part -- ni dans son sens, ni contre. Et chaque aller-retour")
    print(f"  coute {cout:.0f} bps.")
    print()
    print("  Chaque position qu'il n'ouvre pas est de l'argent qu'il ne perd pas.")
    print()
    print("  Ce que ca ne dit PAS : que le systeme est inutile. Ca dit que LE COPY-TRADING n'a pas")
    print("  d'edge. La piste ouverte aujourd'hui est le carnet L2 (encaisser le spread au lieu de")
    print("  le payer) -- elle ne parie sur aucune prediction, et elle n'a jamais ete mesuree.")
    print()

    # etat de la collecte du carnet -- la piste en cours
    l2 = sorted(Path(ROOT / "runtime" / "replay").glob("l2_book*.jsonl"))
    if l2:
        n = sum(1 for f in l2 for _ in f.open("r", encoding="utf-8", errors="ignore"))
        print(f"  Carnet L2 collecte : {n} releves dans {len(l2)} fichier(s). La mesure est possible.")
    else:
        print("  Carnet L2 collecte : AUCUN pour l'instant. Relance le bot et laisse-le tourner")
        print("                       quelques heures, puis relance ce script.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
