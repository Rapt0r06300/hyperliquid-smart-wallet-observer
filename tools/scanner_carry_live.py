"""LE SCANNER CARRY, EN VRAI — **ce que le bot va réellement ouvrir.**

Chaîne complète, sans raccourci :

    funding 365 j (mesuré)  ->  SCANNER (4 portes)  ->  **NOYAU** (7 portes)  ->  PaperIntent

Le scanner **PROPOSE**. Le noyau **DISPOSE** : frais réels (9 bps), plancher net (30 bps),
disjoncteur de session (11 gates V19), `only_per_side`, VPIN, contraintes d'exchange.
***Aucune porte n'est sautée.***

Aucun ordre réel. Paper-only.
"""
from __future__ import annotations

import asyncio
import collections
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.decision_engine.noyau_unique import (  # noqa: E402
    Contexte,
    decider,
)
from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient  # noqa: E402
from hl_observer.strategies.carry_scanner import (  # noqa: E402
    charger_spot_carryables,
    rapport,
    scanner,
)

FUNDING = RACINE / "runtime" / "history" / "funding.jsonl"
SPOT = RACINE / "data" / "reports" / "spot_hl.json"
SORTIE = RACINE / "data" / "reports" / "carry_propositions.json"

NOTIONNEL = 500.0          # marge 50 $ x levier 10


def main() -> int:
    print("=" * 96)
    print("  LE SCANNER CARRY — **ce que le bot va réellement ouvrir**")
    print("  funding 365 j (mesuré) -> SCANNER (4 portes) -> **NOYAU** (7 portes) -> PaperIntent")
    print("=" * 96)

    spot = charger_spot_carryables(SPOT)
    if not spot:
        print("\n  🔴 liste des spot ABSENTE. Lancer `tools/lister_spot_hl.py`.")
        print("     *Je ne devine pas : c'est l'erreur qui m'a fait supposer {HYPE, PURR}.*")
        return 1

    if not FUNDING.exists():
        print("\n  🔴 funding ABSENT. Lancer `tools/backfill_funding.py --jours=365`.")
        return 1

    par: dict[str, list[float]] = collections.defaultdict(list)
    for ligne in FUNDING.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ligne)
            par[str(d["coin"]).upper()].append(float(d["funding"]) * 1e4)
        except Exception:  # noqa: BLE001
            continue

    print("\n  spot carryables (MESURÉS via `spotMeta`, jamais supposés) : %s"
          % ", ".join(sorted(spot)))
    print("  coins avec du funding backfillé : %d" % len(par))

    props = scanner(dict(par), spot_carryables=spot, notional_usd=NOTIONNEL)

    print("\n" + "-" * 96)
    print("  ÉTAPE 1 — LE SCANNER (4 portes)")
    print("-" * 96)
    print("\n  %-8s %10s %7s %9s %8s  %s"
          % ("coin", "fund/h", "%h>0", "APR", "retenu", "motif"))
    for p in props:
        print("  %-8s %+10.4f %6.0f%% %+8.2f%% %8s  %s"
              % (p.coin, p.funding_bps_h, p.part_heures_positives * 100,
                 p.apr_sur_capital * 100, "✅" if p.retenu else "🔴", p.motif[:44]))

    retenus = [p for p in props if p.retenu]

    print("\n" + "-" * 96)
    print("  ÉTAPE 2 — **LE NOYAU** (il rejuge TOUT : frais, plancher, session, VPIN, exchange)")
    print("-" * 96)

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🔴 LE CARNET RÉEL — *un edge sur un carnet de 3 $ n'existe pas.*
    #
    # Le noyau refusait sur `NOYAU_PRIX_NON_EXECUTABLE` : **je ne lui donnais pas le carnet.**
    # Et il avait raison de refuser -- ***on n'invente jamais un prix pour combler un trou.***
    #
    # On va donc chercher le VRAI carnet L2 du perp, et on le lui donne. S'il est trop mince
    # pour 500 $, **le noyau refusera** -- et ce refus sera la mesure, pas une supposition.
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🔴🔴 ET LE CARNET **SPOT** — *un carry a DEUX jambes. On n'en verifiait qu'UNE.*
    #    Mesure : le carnet spot de **PUMP** ne peut pas absorber 500 $ (**473 $ dispo**).
    #    ***Un carry dont la jambe spot ne se remplit pas est un short perp A NU.***
    #    `l2Book` prend le nom de la **PAIRE** (`PURR/USDC`, `@107`), pas du jeton.
    #    -> on CONSTRUIT le mapping depuis `spotMeta`. **On ne le devine pas.**
    async def _carnets() -> tuple[dict[str, dict], dict[str, dict], dict[str, str]]:
        perp: dict[str, dict] = {}
        spot_b: dict[str, dict] = {}
        paires: dict[str, str] = {}
        async with HyperliquidInfoClient() as c:
            meta = await c.spot_meta()
            idx = {str(t["name"]).upper(): int(t["index"])
                   for t in meta.get("tokens", [])
                   if isinstance(t, dict) and "name" in t and "index" in t}
            usdc = idx.get("USDC", 0)
            for u in meta.get("universe", []):
                if not isinstance(u, dict):
                    continue
                tk = u.get("tokens") or []
                if len(tk) != 2 or int(tk[1]) != usdc:
                    continue
                for p in retenus:
                    if p.coin in idx and int(tk[0]) == idx[p.coin]:
                        paires[p.coin] = str(u.get("name"))

            for p in retenus:
                try:
                    perp[p.coin] = await c.l2_book(p.coin)
                except Exception:  # noqa: BLE001
                    perp[p.coin] = {}         # carnet absent -> le noyau REFUSERA. Pas d'invention.
                await asyncio.sleep(0.15)

                paire = paires.get(p.coin)
                if paire:
                    try:
                        spot_b[p.coin] = await c.l2_book(paire)
                    except Exception:  # noqa: BLE001
                        spot_b[p.coin] = {}   # -> REFUS_JAMBE_SPOT_IMPOSSIBLE. C'est VOULU.
                    await asyncio.sleep(0.15)
                else:
                    spot_b[p.coin] = {}       # pas de paire spot -> **ce n'est pas un carry**
        return perp, spot_b, paires

    books, books_spot, paires = asyncio.run(_carnets())
    print("\n  paires SPOT resolues (via `spotMeta`, jamais devinees) : %s"
          % (", ".join("%s->%s" % (k, v) for k, v in sorted(paires.items())) or "**AUCUNE**"))

    def _niveaux(b: dict, cote: int) -> list[tuple[float, float]] | None:
        """(px, sz) depuis le carnet REEL. `None` si illisible -> **le noyau refuse.**"""
        lv = b.get("levels") if isinstance(b, dict) else None
        if not isinstance(lv, list) or len(lv) != 2 or not isinstance(lv[cote], list):
            return None
        out: list[tuple[float, float]] = []
        for n in lv[cote]:
            try:
                out.append((float(n["px"]), float(n["sz"])))
            except (KeyError, TypeError, ValueError):
                continue
        return out or None

    ouvertures = []
    intentions = []
    for p in retenus:
        b = books.get(p.coin, {})
        bs = books_spot.get(p.coin, {})
        d = decider(Contexte(
            strategie="CARRY",                 # -> famille CARRY_STRUCTUREL (PAS une zone morte)
            coin=p.coin,
            direction=p.direction,
            notional_usd=NOTIONNEL,
            niveaux_achat=_niveaux(b, 1),      # asks PERP (on paye)
            niveaux_vente=_niveaux(b, 0),      # bids PERP (on encaisse)
            # 🔴 LA 2e JAMBE. Absente ou trop mince -> **REFUS_JAMBE_SPOT_IMPOSSIBLE.**
            niveaux_spot_achat=_niveaux(bs, 1),   # asks SPOT (on ACHETE le spot)
            niveaux_spot_vente=_niveaux(bs, 0),   # bids SPOT (on le REVENDRA)
            ouvertures_en_cours=tuple(ouvertures),
        ))
        etat = "✅ ENTREE" if d.autorise else "🔴 NO_TRADE"
        print("\n  %-8s %s" % (p.coin, etat))
        print("      raison  : %s" % d.raison)
        if d.signalements:
            print("      signaux : %s" % ", ".join(d.signalements))

        # 🔴 LE SLIPPAGE SPOT — *le prix affiche n'est pas le prix qu'on obtient.*
        sp = (d.preuve or {}).get("spot")
        if isinstance(sp, dict):
            if "slippage_total_bps" in sp:
                print("      spot    : slippage %.2f bps sur les 2 jambes spot"
                      % sp["slippage_total_bps"])
            if "motif" in sp:
                print("      spot    : %s" % sp["motif"])
        elif isinstance(sp, str):
            print("      spot    : %s" % sp)

        if d.autorise:
            ouvertures.append(p.direction)

            # ═══════════════════════════════════════════════════════════════════════════════════
            # 🔑 L'APR PUBLIE = celui d'APRES **TOUT** le slippage. **Jamais le chiffre d'avant.**
            #
            # 🔴 BUG CORRIGE ICI MEME : je ne soustrayais que le slippage **SPOT**, pas celui du
            #    **PERP**. -> le scanner annoncait **+8,42 %** quand la mesure complete disait
            #    **+6,62 %**. ***Deux nombres pour la meme chose : l'un des deux ment.***
            #
            # `d.slippage_bps` est le TOTAL calcule par le noyau (perp via `jambe_executable`
            # **+** spot via `marcher_dans_le_carnet`). *Une seule source, un seul chiffre.*
            # ═══════════════════════════════════════════════════════════════════════════════════
            slip_total = float(getattr(d, "slippage_bps", 0.0) or 0.0)
            apr_apres = p.apr_sur_capital - (slip_total * (24 * 365 / 720.0) / 2.0) / 1e4
            print("      APR     : %+.2f %% (avant slippage) -> **%+.2f %% APRES** "
                  "(slippage total %.2f bps : perp + spot)"
                  % (p.apr_sur_capital * 100, apr_apres * 100, slip_total))
            intentions.append({
                "coin": p.coin, "strategie": "CARRY", "direction": p.direction,
                "notional_usd": NOTIONNEL,
                "funding_bps_h": round(p.funding_bps_h, 4),
                "apr_avant_slippage_pct": round(p.apr_sur_capital * 100, 2),
                "slippage_total_bps": round(slip_total, 2),
                "apr_sur_capital_pct": round(apr_apres * 100, 2),   # **le chiffre HONNETE**
                "raison": d.raison,
                "paper_intent": True, "real_execution": False,
            })

    print("\n" + "=" * 96)
    print("  RÉSULTAT")
    print("=" * 96)
    print("\n  scannés  : %d coins" % len(props))
    print("  retenus par le SCANNER : %d" % len(retenus))
    print("  **AUTORISÉS PAR LE NOYAU : %d**" % len(intentions))
    for x in intentions:
        print("     ✅ %-8s CARRY %s  %+.2f %% APR  (funding %+.4f bps/h)"
              % (x["coin"], x["direction"], x["apr_sur_capital_pct"], x["funding_bps_h"]))

    if not intentions:
        print("\n  ⚪ **Aucune ouverture.** Ce n'est pas une panne : c'est le système qui refuse.")
        print("     *Zéro trade vaut mieux qu'un mauvais trade.*")

    print("\n  🚩 **CE QUE CES CHIFFRES NE SONT PAS** :")
    print("     - une promesse. Le funding **peut s'inverser** (BERA : -0,83 · TRUMP : -0,28).")
    print("     - un chèque. **La profondeur du carnet reste à vérifier** : *un edge sur un")
    print("       carnet de 3 $ n'existe pas.*")
    print("     - sans risque. **La jambe perp peut être LIQUIDÉE** (X-08).")
    print("     - un vainqueur. **Il doit encore battre un dépôt passif dans HLP.**")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({
        "propositions": [p.as_dict() for p in props],
        "autorisees_par_le_noyau": intentions,
        "rapport": rapport(props),
        "paper_only": True, "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % SORTIE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
