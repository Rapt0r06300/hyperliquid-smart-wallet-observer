#!/usr/bin/env python3
"""DIAGNOSTIC BRUT DU MARCHE SPOT HYPERLIQUID (2026-07-12).

POURQUOI CE SCRIPT EXISTE
-------------------------
`mesurer_carry_neutre.py` a sorti des chiffres IMPOSSIBLES :

    HYPE   base = +177 721 383 bps   -> le perp vaudrait 17 772 x le spot
    HYPE   spot 24h = 0 $            -> alors que c'est le token maison d'Hyperliquid

Un chiffre impossible ne se commente pas : il se DEBOGUE. Ce script ne calcule RIEN.
Il DUMPE la structure reelle du payload `spotMetaAndAssetCtxs` pour qu'on arrete de deviner
les noms de champs et l'alignement des tableaux.

REGLE DU PROJET : on n'enterre pas une piste sur une mesure fausse. On repare la mesure d'abord.

    python tools/diagnostic_spot_hyperliquid.py

LECTURE SEULE. Endpoint /info public. Aucune cle, aucune signature, aucun ordre. JAMAIS.
"""
from __future__ import annotations

import json
import sys
import urllib.request

API = "https://api.hyperliquid.xyz/info"

# Les coins qui DECIDENT : soit ils ont un spot exploitable, soit le carry delta-neutre est mort.
INTERESSANTS = ["HYPE", "PURR", "VINE", "POL", "LIT", "ZRO", "HEMI", "APEX", "ACE", "SYRUP",
                "SAGA", "ZEC", "TRUMP", "BERA", "PUMP", "AZTEC", "MON", "STABLE"]


def _post(payload: dict):
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=20.0) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    print("\n" + "=" * 78)
    print("  DIAGNOSTIC BRUT — SPOT HYPERLIQUID (on arrete de deviner)")
    print("=" * 78 + "\n")

    try:
        spot = _post({"type": "spotMetaAndAssetCtxs"})
    except Exception as exc:
        print("  ECHEC reseau : %s\n" % exc)
        return 3

    if not (isinstance(spot, list) and len(spot) == 2):
        print("  STRUCTURE INATTENDUE : %r\n" % type(spot))
        return 2

    meta, ctxs = spot[0], spot[1]
    tokens = meta.get("tokens") or []
    universe = meta.get("universe") or []

    print("  tokens   : %d" % len(tokens))
    print("  universe : %d paires" % len(universe))
    print("  assetCtxs: %d       <-- si != universe, l'alignement zip() est FAUX\n" % len(ctxs))

    # ---------------------------------------------------------------- 1. les CLES reelles
    if tokens:
        print("  CLES d'un token   : %s" % sorted(tokens[0].keys()))
    if universe:
        print("  CLES d'une paire  : %s" % sorted(universe[0].keys()))
    if ctxs and isinstance(ctxs[0], dict):
        print("  CLES d'un ctx     : %s" % sorted(ctxs[0].keys()))
    print()

    print("  ECHANTILLON BRUT (paire 0) :")
    if universe:
        print("    universe[0] = %s" % json.dumps(universe[0], ensure_ascii=False))
    if ctxs:
        print("    ctxs[0]     = %s" % json.dumps(ctxs[0], ensure_ascii=False))
    print()

    # ---------------------------------------------------------------- 2. table des tokens
    par_index = {}
    for t in tokens:
        try:
            par_index[int(t["index"])] = str(t.get("name") or "").upper()
        except (KeyError, TypeError, ValueError):
            continue

    # ---------------------------------------------------------------- 3. les paires qui comptent
    print("  " + "-" * 74)
    print("  LES PAIRES SPOT DES COINS QUI DECIDENT")
    print("  " + "-" * 74)
    print("  %-10s %-12s %14s %16s %10s" % ("coin", "paire", "markPx", "dayNtlVlm", "ctx#"))
    print("  %-10s %-12s %14s %16s %10s" % ("-" * 10, "-" * 12, "-" * 14, "-" * 16, "-" * 10))

    trouves = set()
    for i, pair in enumerate(universe):
        idx = pair.get("tokens") or []
        base = par_index.get(idx[0]) if idx else None
        if base not in INTERESSANTS:
            continue
        c = ctxs[i] if i < len(ctxs) and isinstance(ctxs[i], dict) else {}
        # on affiche TOUS les champs de prix candidats, sans en privilegier un
        mark = c.get("markPx")
        mid = c.get("midPx")
        vol = c.get("dayNtlVlm")
        nom_paire = str(pair.get("name") or "?")
        print("  %-10s %-12s %14s %16s %10d" % (base, nom_paire, mark, vol, i))
        if mid is not None and mid != mark:
            print("             (midPx = %s)" % mid)
        trouves.add(base)

    print()
    manquants = [c for c in INTERESSANTS if c not in trouves]
    if manquants:
        print("  AUCUNE PAIRE SPOT pour : %s" % ", ".join(manquants))
        print("  -> pour ces coins, la couverture spot sur Hyperliquid est IMPOSSIBLE.")
        print("     (ce n'est pas un bug de lecture : la paire n'existe pas)\n")

    # ---------------------------------------------------------------- 4. le top spot reel
    print("  " + "-" * 74)
    print("  LES 15 PLUS GROS MARCHES SPOT (par dayNtlVlm) — controle de bon sens")
    print("  " + "-" * 74)
    rangs = []
    for i, pair in enumerate(universe):
        c = ctxs[i] if i < len(ctxs) and isinstance(ctxs[i], dict) else {}
        idx = pair.get("tokens") or []
        base = par_index.get(idx[0]) if idx else "?"
        try:
            vol = float(c.get("dayNtlVlm") or 0.0)
        except (TypeError, ValueError):
            vol = 0.0
        rangs.append((vol, base, str(pair.get("name") or "?"), c.get("markPx")))
    rangs.sort(reverse=True)
    for vol, base, nom, mark in rangs[:15]:
        print("  %-10s %-12s  vol24 = %14.0f $   markPx = %s" % (base, nom, vol, mark))

    total = sum(v for v, _, _, _ in rangs)
    print("\n  volume spot TOTAL 24 h : %.0f $" % total)
    if total <= 0:
        print("  >>> UN VOLUME TOTAL DE ZERO EST IMPOSSIBLE. Le champ lu n'est pas le bon.")
        print("      Regarde les CLES d'un ctx ci-dessus et corrige le nom du champ.\n")
    else:
        print("  >>> Volume non nul : le champ `dayNtlVlm` est le bon. Les zeros affiches")
        print("      sont alors de VRAIS marches spot morts, pas une erreur de lecture.\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
