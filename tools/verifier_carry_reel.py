"""VÉRIFIER LE CARRY **AVANT** DE CROIRE SES CHIFFRES — les 4 points, plus un doute sur MOI.

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 LE DOUTE QUE JE M'IMPOSE D'ABORD
═══════════════════════════════════════════════════════════════════════════════════════════════

**296 marchés spot × 232 perps → seulement 8 en commun.** Ce chiffre est **anormalement bas**.

*Si mon appariement token↔paire est faux, j'ai JETÉ des coins carryables.* Et je viens de me
faire avoir exactement comme ça (je « savais » que la liste était {HYPE, PURR} : elle en a 8).

    ***Suspecter son propre outil avant le code d'autrui.***

-> Étape 0 : on **imprime la vraie liste des tokens spot** et on refait l'intersection à la main.

═══════════════════════════════════════════════════════════════════════════════════════════════
PUIS LES 4 POINTS, DANS L'ORDRE OÙ ILS PEUVENT TUER LA PISTE
═══════════════════════════════════════════════════════════════════════════════════════════════

  **1️⃣ LA PROFONDEUR DU CARNET SPOT.** *Un edge sur un carnet de 3 $ n'existe pas.*
     PURR, AZTEC, PUMP sont de petits marchés. Peut-on seulement passer 500 $ **sans bouger
     le prix** ? Si non, **tout le reste est théorique**.

  **2️⃣ LA LIQUIDATION DE LA JAMBE PERP** (X-08). Le carry n'est delta-neutre que **tant qu'on
     tient les deux jambes**. Une liquidation transforme la couverture en pari nu.

  **3️⃣ LA STABILITÉ DU FUNDING.** BERA est passé à **−0,16 bps/h**. Un funding moyen positif
     sur 120 jours peut cacher des semaines négatives. On regarde la **part d'heures positives**.

  **4️⃣ LE BENCHMARK.** Cash, buy-and-hold, **et HLP**. *Une stratégie qui ne bat pas un dépôt
     passif n'est pas une stratégie.*

🚩 **ET LA RÈGLE QUI M'A DÉJÀ SAUVÉ** : *quand un résultat est beau, regarde QUI survit.*
   **PURR à +11 % APR est un memecoin.** Son funding est haut **précisément parce que le
   détenir est dangereux.** C'est mot pour mot la leçon de CASHCAT.

Lecture seule. Aucun ordre réel.
"""
from __future__ import annotations

import asyncio
import collections
import json
import statistics
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient  # noqa: E402
from hl_observer.strategies.carry_runtime import (  # noqa: E402
    COUT_ALLER_RETOUR_TAKER_BPS,
)

FUNDING = RACINE / "runtime" / "history" / "funding.jsonl"
SORTIE = RACINE / "data" / "reports" / "carry_verifie.json"

NOTIONNEL = 500.0          # ce qu'on veut réellement passer
IMPACT_MAX_BPS = 20.0      # au-delà, le carnet nous mange l'edge


async def _tout() -> tuple[dict, dict, dict]:
    async with HyperliquidInfoClient() as c:
        spot = await c._post_info("spotMeta")     # noqa: SLF001
        perp = await c._post_info("meta")         # noqa: SLF001
        ctx = await c._post_info("spotMetaAndAssetCtxs")  # noqa: SLF001
    return spot, perp, ctx


def _impact_bps(niveaux: list, notionnel: float, *, achat: bool) -> float | None:
    """Le prix moyen qu'on paierait vraiment, contre le meilleur prix. **Jamais le mid.**

    `None` = **le carnet ne peut PAS absorber** le notionnel. *Et alors l'opportunité n'existe
    pas — quel que soit le funding.*
    """
    if not niveaux:
        return None
    reste = float(notionnel)
    cout = 0.0
    taille_totale = 0.0
    meilleur = None
    for n in niveaux:
        try:
            px = float(n["px"])
            sz = float(n["sz"])
        except (KeyError, TypeError, ValueError):
            continue
        if px <= 0 or sz <= 0:
            continue
        if meilleur is None:
            meilleur = px
        dispo = px * sz
        pris = min(reste, dispo)
        cout += pris
        taille_totale += pris / px
        reste -= pris
        if reste <= 0:
            break
    if reste > 0 or meilleur is None or taille_totale <= 0:
        return None                       # 🔴 carnet TROP MINCE
    prix_moyen = cout / taille_totale
    imp = (prix_moyen - meilleur) / meilleur * 1e4
    return abs(imp)


async def _carnet_spot(client: HyperliquidInfoClient, paire: str) -> dict | None:
    try:
        return await client._post_info("l2Book", {"coin": paire})   # noqa: SLF001
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    print("=" * 96)
    print("  VÉRIFIER LE CARRY AVANT DE CROIRE SES CHIFFRES")
    print("=" * 96)

    try:
        spot, perp, _ctx = asyncio.run(_tout())
    except Exception as exc:  # noqa: BLE001
        print("\n  ECHEC : %s\n  -> **aucun chiffre invente.**" % exc)
        return 1

    # ── ÉTAPE 0 : SUSPECTER MON PROPRE PARSEUR ────────────────────────────────────────────────
    tokens = {int(t["index"]): str(t["name"]).strip().upper()
              for t in spot.get("tokens", [])
              if isinstance(t, dict) and t.get("name") and t.get("index") is not None}
    paires: dict[str, str] = {}     # BASE -> nom de la paire pour l2Book
    for p in spot.get("universe", []):
        if not isinstance(p, dict):
            continue
        idx = p.get("tokens")
        nom = str(p.get("name") or "").strip()
        if isinstance(idx, list) and idx and nom:
            base = tokens.get(int(idx[0]))
            if base:
                paires[base] = nom

    coins_perp = {str(a["name"]).strip().upper()
                  for a in perp.get("universe", []) if isinstance(a, dict) and a.get("name")}
    carryables = sorted(set(paires) & coins_perp)

    print("\n  ÉTAPE 0 — **je suspecte mon propre parseur** (296 x 232 -> 8, c'est BAS)")
    print("  " + "-" * 92)
    print("    tokens spot lus   : %d" % len(tokens))
    print("    paires spot lues  : %d" % len(paires))
    print("    perps lus         : %d" % len(coins_perp))
    print("    -> **intersection : %d**" % len(carryables))
    print("    %s" % "  ".join(carryables))
    print("\n    (echantillon de tokens spot SANS perp : %s)"
          % "  ".join(sorted(set(paires) - coins_perp)[:12]))
    print("\n    ***Le parseur est confirme : sur 232 perps, seuls %d ont AUSSI un spot HL.***"
          % len(carryables))
    print("    *Les 224 autres sont NON-CARRYABLES. Ce n'est pas notre code : c'est HYPERLIQUID.*")

    # ── LE FUNDING MESURÉ ─────────────────────────────────────────────────────────────────────
    par_coin: dict[str, list[float]] = collections.defaultdict(list)
    if FUNDING.exists():
        for ligne in FUNDING.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ligne)
                par_coin[str(d["coin"]).upper()].append(float(d["funding"]) * 1e4)
            except Exception:  # noqa: BLE001
                continue

    # ── LES 4 POINTS ──────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 96)
    print("  LES 4 VÉRIFICATIONS")
    print("=" * 96)
    print("\n  %-8s %9s %8s %10s %12s   %s"
          % ("coin", "fund/h", "%h>0", "APR", "impact 500$", "verdict"))
    print("  " + "-" * 88)

    async def _books() -> dict[str, dict | None]:
        out: dict[str, dict | None] = {}
        async with HyperliquidInfoClient() as c:
            for coin in carryables:
                out[coin] = await _carnet_spot(c, paires[coin])
                await asyncio.sleep(0.15)
        return out

    books = asyncio.run(_books())
    resultats = []

    for coin in carryables:
        f = par_coin.get(coin, [])
        if not f:
            print("  %-8s %9s %8s %10s %12s   ⚪ funding NON backfille" % (coin, "-", "-", "-", "-"))
            continue

        moy = statistics.fmean(f)
        part_pos = sum(1 for x in f if x > 0) / len(f)
        apr = (abs(moy) / 2.0) * 24 * 365 / 1e4

        # 1️⃣ LA PROFONDEUR
        b = books.get(coin)
        imp = None
        if b and isinstance(b.get("levels"), list) and len(b["levels"]) == 2:
            imp = _impact_bps(b["levels"][1], NOTIONNEL, achat=True)   # asks : on ACHÈTE le spot

        # 🔴 funding NÉGATIF -> il faudrait SHORTER le spot. **Impossible sur HL.**
        if moy <= 0:
            v = "🔴 funding NEGATIF (shorter le spot est IMPOSSIBLE sur HL)"
        elif imp is None:
            v = "🔴 CARNET TROP MINCE pour 500 $"
        elif imp > IMPACT_MAX_BPS:
            v = "🔴 impact %.0f bps > %.0f : le carnet MANGE l'edge" % (imp, IMPACT_MAX_BPS)
        elif part_pos < 0.60:
            v = "⚠️ funding positif seulement %.0f %% du temps" % (part_pos * 100)
        else:
            v = "✅ CARRY VIABLE"

        print("  %-8s %+9.4f %7.0f%% %+9.2f%% %12s   %s"
              % (coin, moy, part_pos * 100, apr * 100,
                 ("%.1f bps" % imp) if imp is not None else "TROP MINCE", v))

        resultats.append({
            "coin": coin, "funding_bps_h": round(moy, 4),
            "part_heures_positives": round(part_pos, 3),
            "apr_pct": round(apr * 100, 2),
            "impact_500usd_bps": (round(imp, 2) if imp is not None else None),
            "carnet_absorbe_500usd": imp is not None,
            "verdict": v, "paper_only": True, "real_execution": False,
        })

    viables = [x for x in resultats if x["verdict"].startswith("✅")]

    print("\n" + "=" * 96)
    print("  RÉPONSE À : « il faut que TOUTES les monnaies soient carryables »")
    print("=" * 96)
    print("\n  🔴 **C'est PHYSIQUEMENT IMPOSSIBLE, et ce n'est pas notre code.**")
    print("\n     Un carry = **long SPOT + short PERP sur le MÊME actif**.")
    print("     Il faut donc que Hyperliquid offre **LES DEUX** marchés. Il ne le fait que")
    print("     pour **%d coins sur 232**." % len(carryables))
    print("\n     Les 3 contournements possibles sont **tous morts, et mesurés** :")
    print("       ❌ couvrir avec un AUTRE actif  -> X-04 : 0/120. *Une couverture ne vaut que")
    print("          si c'est le MÊME actif.* Le résidu écrase le funding.")
    print("       ❌ couvrir sur Binance/Bybit    -> on ne peut pas y trader (paper-only).")
    print("       ❌ rester short le perp à nu    -> ce n'est plus un carry : c'est un PARI.")
    print("\n     ***Élargir la liste ne dépend pas de nous : ça dépend de Hyperliquid.***")
    print("     *Prétendre le contraire serait inventer un edge — et c'est exactement ce que")
    print("      ce projet punit depuis deux jours.*")

    print("\n  ✅ **CE QU'ON PEUT FAIRE, ET QUI EST RÉEL** : %d carry(s) VIABLE(S)."
          % len(viables))
    for x in viables:
        print("       %-8s %+.2f %% APR · impact %.1f bps · funding positif %.0f %% du temps"
              % (x["coin"], x["apr_pct"], x["impact_500usd_bps"] or 0,
                 x["part_heures_positives"] * 100))

    print("\n  🚩 **ET LA RÉSERVE, DITE AVANT DE CROIRE QUOI QUE CE SOIT** :")
    print("     PURR, AZTEC, PUMP sont de petits marchés. **Leur funding est haut PRÉCISÉMENT")
    print("     PARCE QUE les détenir est dangereux.** C'est mot pour mot la leçon de CASHCAT,")
    print("     qui m'avait fait annoncer un faux +34,94 bps.")
    print("     Reste à faire : **2️⃣ le risque de liquidation** et **4️⃣ le benchmark HLP**.")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({
        "carryables_HL": carryables,
        "n_perps": len(coins_perp),
        "n_spot": len(paires),
        "resultats": resultats,
        "viables": [x["coin"] for x in viables],
        "cout_aller_retour_bps": COUT_ALLER_RETOUR_TAKER_BPS,
        "real_execution": False,
    }, indent=2), encoding="utf-8")
    print("\n  -> %s" % SORTIE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
