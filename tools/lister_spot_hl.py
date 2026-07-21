"""LA VRAIE LISTE DES MARCHÉS SPOT HYPERLIQUID — **et donc des carrys POSSIBLES.**

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI CET OUTIL EXISTE
═══════════════════════════════════════════════════════════════════════════════════════════════

Le carry **EXIGE** une jambe spot :

    long SPOT + short PERP  ->  delta-neutre. On encaisse le funding sans parier sur le prix.

**Sans spot, on est short le perp À NU** — c'est-à-dire un **pari directionnel** déguisé en carry.

🔴 **ET J'AI SUPPOSÉ LA LISTE.** J'avais écrit `SPOT_HL_CONNU = {"HYPE", "PURR"}` — de mémoire,
sans jamais le vérifier. *C'est exactement l'erreur qui m'a fait déclarer « data-limited » ce qui
était à un appel de distance, et « pas de source historique » ce qui existait depuis 2023.*

    ***On demande à l'API. On ne devine pas.***

`spotMeta` est un endpoint **public**, /info, sans wallet, sans signature.

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE L'OUTIL FAIT
═══════════════════════════════════════════════════════════════════════════════════════════════

  1. récupère **tous** les marchés spot HL (`spotMeta`) ;
  2. les croise avec les **perps** (`meta`) ;
  3. -> **l'intersection EST la liste des carrys physiquement possibles.**

⚠️ Un coin qui a un perp mais **pas** de spot est **NON-CARRYABLE**. Point.
*Aucun contournement : couvrir avec un AUTRE actif est mort (X-04), et on ne peut pas trader
ailleurs.*

Lecture seule. Aucun ordre réel. Aucune clé.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient  # noqa: E402

SORTIE = RACINE / "data" / "reports" / "spot_hl.json"


async def _recuperer() -> tuple[list[str], list[str]]:
    """(coins SPOT, coins PERP). DENY-BY-DEFAULT : une entree illisible est ECARTEE."""
    async with HyperliquidInfoClient() as c:
        spot = await c._post_info("spotMeta")            # noqa: SLF001 — /info, allowlist
        perp = await c._post_info("meta")                # noqa: SLF001

    coins_spot: list[str] = []
    if isinstance(spot, dict):
        # `tokens` = les tokens ; `universe` = les PAIRES (ex. "@107" ou "HYPE/USDC")
        tokens = {int(t["index"]): str(t["name"]).strip().upper()
                  for t in spot.get("tokens", [])
                  if isinstance(t, dict) and t.get("name") and t.get("index") is not None}
        for p in spot.get("universe", []):
            if not isinstance(p, dict):
                continue
            idx = p.get("tokens")
            if isinstance(idx, list) and idx:
                base = tokens.get(int(idx[0]))
                if base:
                    coins_spot.append(base)

    coins_perp: list[str] = []
    if isinstance(perp, dict):
        coins_perp = [str(a["name"]).strip().upper()
                      for a in perp.get("universe", [])
                      if isinstance(a, dict) and a.get("name")]

    return sorted(set(coins_spot)), sorted(set(coins_perp))


def main() -> int:
    print("=" * 92)
    print("  LA VRAIE LISTE DES MARCHES SPOT HYPERLIQUID")
    print("  (je la SUPPOSAIS : {HYPE, PURR}. **On demande a l'API. On ne devine pas.**)")
    print("=" * 92)

    try:
        spot, perp = asyncio.run(_recuperer())
    except Exception as exc:  # noqa: BLE001
        print("\n  ECHEC de l'appel : %s" % exc)
        print("  -> **AUCUNE liste inventee.** Etat vide honnete.")
        return 1

    if not spot or not perp:
        print("\n  Reponse vide. **Aucune liste inventee.**")
        return 1

    carryables = sorted(set(spot) & set(perp))
    perp_sans_spot = sorted(set(perp) - set(spot))

    print("\n  marches SPOT  : %d" % len(spot))
    print("  marches PERP  : %d" % len(perp))
    print("-" * 92)
    print("\n  🎯 **CARRYABLES** (perp **ET** spot -> delta-neutre POSSIBLE) : **%d**"
          % len(carryables))
    for i in range(0, len(carryables), 10):
        print("     " + "  ".join(carryables[i:i + 10]))

    print("\n  🔴 **PERP SANS SPOT** (carry IMPOSSIBLE — ce serait un short perp A NU) : %d"
          % len(perp_sans_spot))
    apercu = perp_sans_spot[:20]
    for i in range(0, len(apercu), 10):
        print("     " + "  ".join(apercu[i:i + 10]))
    if len(perp_sans_spot) > 20:
        print("     ... et %d autres" % (len(perp_sans_spot) - 20))

    # Les coins qu'on a backfillés en funding : lesquels sont carryables ?
    NOS_COINS = ["BTC", "ETH", "SOL", "BNB", "AVAX", "ARB", "DOGE", "LTC", "SUI", "OP",
                 "HYPE", "NEAR"]
    print("\n" + "=" * 92)
    print("  NOS 12 COINS BACKFILLES — lesquels peuvent VRAIMENT porter un carry ?")
    print("=" * 92)
    ok = [c for c in NOS_COINS if c in carryables]
    ko = [c for c in NOS_COINS if c not in carryables]
    print("\n  ✅ CARRYABLES : %s" % (", ".join(ok) if ok else "**AUCUN**"))
    print("  🔴 IMPOSSIBLES : %s" % ", ".join(ko))

    print("\n" + "-" * 92)
    if not ok:
        print("  🔴 **AUCUN de nos coins backfilles n'a de spot HL.**")
        print("     La contrainte est REELLE. **Il n'y a rien a « arranger ».**")
        print("     *Pretendre le contraire serait inventer un edge.*")
    else:
        print("  🎯 **%d coin(s) peuvent porter un carry delta-neutre.**" % len(ok))
        print("     -> relancer `LANCER-LE-CARRY.cmd` : le moteur les prendra tous.")
    print("\n  ⚠️ Il reste %d marches spot qu'on n'a PAS backfilles en funding." % (
        len(carryables) - len(ok)))
    print("     **C'est la vraie piste d'elargissement** : backfiller leur funding et voir.")
    print("-" * 92)

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({
        "n_spot": len(spot), "n_perp": len(perp),
        "carryables": carryables,
        "nos_coins_carryables": ok,
        "nos_coins_impossibles": ko,
        "spot": spot,
        "real_execution": False,
    }, indent=2), encoding="utf-8")
    print("\n  -> %s" % SORTIE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
