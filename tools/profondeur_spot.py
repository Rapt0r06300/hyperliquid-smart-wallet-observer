"""LA PROFONDEUR DU CARNET SPOT — *un edge sur un carnet de 3 $ n'existe pas.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LE DERNIER RISQUE NON MESURE — et il peut TOUT annuler
═══════════════════════════════════════════════════════════════════════════════════════════════

Le bot ouvre 3 carrys : **PURR (+11,31 %) · PUMP (+5,23 %) · HYPE (+4,48 %)**, au NET.

Mais ces APR supposent qu'on peut **acheter le spot** pour 500 $ **au prix affiche**.

    ***Ce sont de PETITS marches. Leur funding est eleve PRECISEMENT parce que les detenir
    est dangereux et que peu de gens veulent le faire.***

Si le carnet spot est mince, le **slippage** mange l'edge -- et il le mange **DEUX fois**
(a l'entree et a la sortie). Un carry a 4,48 % d'APR ne survit pas a 50 bps de slippage.

*C'est le meme piege que le market making : le prix affiche n'est pas le prix qu'on obtient.*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QU'ON MESURE
═══════════════════════════════════════════════════════════════════════════════════════════════

  1. le **spread** spot (bid/ask) ;
  2. le **slippage reel** pour acheter notre notionnel (on marche dans le carnet, niveau par
     niveau -- **on ne suppose pas un prix unique**) ;
  3. la **profondeur disponible** en dollars ;
  4. et le verdict : **l'edge survit-il apres le slippage aller-retour ?**

🔒 `l2Book` est /info, public, lecture seule. **Aucun ordre. Aucune signature. Paper-only.**
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient  # noqa: E402
from hl_observer.market.spot_depth import (  # noqa: E402
    marcher_dans_le_carnet,
    niveaux,
    verdict_carry,
)

NOS_COINS = ("PURR", "PUMP", "HYPE")
NOTIONNEL = 500.0

# les APR NETS mesures (apres les 23 bps de frais, avant slippage)
APR_NET = {"PURR": 0.1131, "PUMP": 0.0523, "HYPE": 0.0448}

SORTIE = RACINE / "data" / "reports" / "profondeur_spot.json"


async def _collecte() -> dict:
    out: dict = {"paires": {}, "carnets_spot": {}, "carnets_perp": {}}
    async with HyperliquidInfoClient() as c:
        meta = await c.spot_meta()

        # ── le mapping jeton -> PAIRE. *On le CONSTRUIT ; on ne le devine pas.* ───────────────
        idx = {}
        for t in meta.get("tokens", []):
            if isinstance(t, dict) and "name" in t and "index" in t:
                idx[str(t["name"]).upper()] = int(t["index"])
        usdc = idx.get("USDC", 0)

        for u in meta.get("universe", []):
            if not isinstance(u, dict):
                continue
            tk = u.get("tokens") or []
            if len(tk) != 2 or int(tk[1]) != usdc:
                continue
            for coin in NOS_COINS:
                if coin in idx and int(tk[0]) == idx[coin]:
                    out["paires"][coin] = str(u.get("name"))

        for coin in NOS_COINS:
            paire = out["paires"].get(coin)
            if paire:
                try:
                    out["carnets_spot"][coin] = await c.l2_book(paire)
                except Exception as e:  # noqa: BLE001
                    out["carnets_spot"][coin] = {"_erreur": str(e)}
                await asyncio.sleep(0.15)
            try:
                out["carnets_perp"][coin] = await c.l2_book(coin)
            except Exception as e:  # noqa: BLE001
                out["carnets_perp"][coin] = {"_erreur": str(e)}
            await asyncio.sleep(0.15)
    return out


def main() -> int:  # noqa: C901
    print("=" * 100)
    print("  LA PROFONDEUR DU CARNET SPOT — *un edge sur un carnet de 3 $ n'existe pas.*")
    print("  On MARCHE dans le carnet, niveau par niveau. **On ne suppose aucun prix.**")
    print("=" * 100)

    try:
        d = asyncio.run(_collecte())
    except Exception as e:  # noqa: BLE001
        print("\n  🔴 collecte impossible : %s" % e)
        print("     ***ETAT VIDE HONNETE.*** Sans carnet, **aucun verdict**.")
        return 1

    print("\n  paires spot resolues (via `spotMeta`, jamais devinees) :")
    for c, p in sorted(d["paires"].items()):
        print("     %-8s -> %s" % (c, p))
    manquants = [c for c in NOS_COINS if c not in d["paires"]]
    if manquants:
        print("\n  🔴 **AUCUNE PAIRE SPOT TROUVEE** pour : %s" % ", ".join(manquants))
        print("     ***Sans jambe spot, ce n'est PAS un carry : c'est un short perp A NU.***")

    lignes = []
    for coin in NOS_COINS:
        print("\n" + "─" * 100)
        print("  %s   (APR net mesure : %+.2f %%)" % (coin, APR_NET.get(coin, 0.0) * 100))
        print("─" * 100)

        b_spot = d["carnets_spot"].get(coin) or {}
        b_perp = d["carnets_perp"].get(coin) or {}

        asks = niveaux(b_spot, 1)     # on ACHETE le spot -> on paye les asks
        bids = niveaux(b_spot, 0)     # on le REVENDRA -> on encaissera les bids
        p_asks = niveaux(b_perp, 1)
        p_bids = niveaux(b_perp, 0)

        if not asks or not bids:
            print("    🔴 **CARNET SPOT ILLISIBLE OU VIDE.** -> *etat vide honnete, pas de verdict.*")
            print("       ***Et un carry sans jambe spot n'est pas un carry.***")
            lignes.append({"coin": coin, "spot_lisible": False,
                           "verdict": "CARNET_SPOT_ABSENT_PAS_DE_VERDICT"})
            continue

        achat = marcher_dans_le_carnet(asks, NOTIONNEL)      # entree spot
        vente = marcher_dans_le_carnet(bids, NOTIONNEL)      # sortie spot
        p_achat = marcher_dans_le_carnet(p_bids, NOTIONNEL)  # entree perp (on SHORT -> on vend)
        p_vente = marcher_dans_le_carnet(p_asks, NOTIONNEL)  # sortie perp (on rachete)

        for nom, r, lv in (("SPOT achat ", achat, asks), ("SPOT vente ", vente, bids),
                           ("PERP vente", p_achat, p_bids), ("PERP achat", p_vente, p_asks)):
            dispo = sum(px * sz for px, sz in lv)
            if r.rempli:
                print("    %s : slippage **%6.2f bps**  ·  profondeur dispo %10.0f $"
                      % (nom, r.slippage_bps, dispo))
            else:
                print("    %s : 🔴 **CARNET TROP MINCE** — seulement %.0f $ dispo pour %.0f $ voulus"
                      % (nom, dispo, NOTIONNEL))

        v = verdict_carry(APR_NET.get(coin, 0.0), achat, vente, p_achat, p_vente)
        print("\n    slippage total (4 jambes) : **%.2f bps**" % v.slippage_total_bps)
        print("    APR net APRES slippage    : **%+.2f %%**  (avant : %+.2f %%)"
              % (v.apr_apres_slippage * 100, APR_NET.get(coin, 0.0) * 100))
        print("    -> %s" % v.verdict)

        lignes.append({"coin": coin, "spot_lisible": True,
                       "paire": d["paires"].get(coin),
                       "slippage_total_bps": round(v.slippage_total_bps, 2),
                       "apr_avant_slippage_pct": round(APR_NET.get(coin, 0.0) * 100, 2),
                       "apr_apres_slippage_pct": round(v.apr_apres_slippage * 100, 2),
                       "survit": v.survit, "verdict": v.verdict})

    survivants = [x for x in lignes if x.get("survit")]
    print("\n" + "=" * 100)
    print("  VERDICT FINAL")
    print("=" * 100)
    print("\n  survivent au carnet REEL : %s"
          % (", ".join("%s (%+.2f %%)" % (x["coin"], x["apr_apres_slippage_pct"])
                       for x in survivants) if survivants else "🔴 **AUCUN**"))
    if not survivants:
        print("\n  🔴🔴🔴 **LE CARNET TUE LES TROIS CARRYS.**")
        print("     *Leur funding etait eleve precisement parce que ces marches sont minces.*")
        print("     ***On ne va pas trader un edge qui n'existe qu'au prix affiche.***")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({
        "notionnel_usd": NOTIONNEL, "coins": lignes,
        "survivants": [x["coin"] for x in survivants],
        "paper_only": True, "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % SORTIE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
