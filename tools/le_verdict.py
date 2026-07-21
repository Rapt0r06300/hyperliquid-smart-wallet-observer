"""LE VERDICT — *nos carrys battent-ils un simple VIREMENT ?*

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI CET OUTIL EXISTE
═══════════════════════════════════════════════════════════════════════════════════════════════

Deux choses viennent d'etre trouvees, et elles changent tout :

  🔴 **1. L'APR affiche etait le BRUT.** `carry_runtime.apr_sur_capital` valait
     `(funding / 2) x 24 x 365` -- ***les 23 bps de couts n'y figuraient PAS.*** Ils etaient
     verifies a la porte, puis **jamais soustraits du chiffre**.
     *Un cout qu'on verifie mais qu'on ne soustrait pas est un cout qu'on CACHE.*
     -> corrige. PURR 12,71 -> **11,31 %** · PUMP 6,63 -> **5,23 %** · HYPE 5,87 -> **4,48 %**

  🔴 **2. Le benchmark HLP etait SUPPOSE.** J'avais ecrit « 10 a 30 % APR » **de tete**.
     C'est le peche que ce projet punit : DEVINER au lieu de DEMANDER. (4e fois.)
     -> on le **MESURE** via `vaultDetails`, endpoint public, lecture seule.

***Le benchmark decide de tout.*** Si HLP rend 15 % et notre carry 5 %, alors toute la
complexite qu'on a construite est **dominee par un virement**. Et il faut le DIRE.

🚩 HLP n'est PAS sans risque : il porte l'inventaire et absorbe les liquidations. On compare
donc aussi les **drawdowns**, pas seulement les APR.

Lecture seule. Aucun depot. Aucun ordre reel. Rien de payant.
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
from hl_observer.market.hlp_vault import PRIVILEGES  # noqa: E402
from hl_observer.strategies.carry_runtime import (  # noqa: E402
    COUT_ALLER_RETOUR_MAKER_BPS,
    COUT_ALLER_RETOUR_TAKER_BPS,
    CandidatCarry,
    evaluer,
)
from hl_observer.strategies.carry_scanner import charger_spot_carryables  # noqa: E402

# L'adresse publique du vault HLP (le market maker officiel de Hyperliquid).
HLP = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"

FUNDING = RACINE / "runtime" / "history" / "funding.jsonl"
SPOT = RACINE / "data" / "reports" / "spot_hl.json"
SORTIE = RACINE / "data" / "reports" / "le_verdict.json"


def _drawdown(v: list[float]) -> float:
    s, pire = (v[0] if v else 0.0), 0.0
    for x in v:
        s = max(s, x)
        if s > 0:
            pire = max(pire, (s - x) / s)
    return pire


async def _hlp() -> dict:
    async with HyperliquidInfoClient() as c:
        return await c.vault_details(HLP)


def main() -> int:  # noqa: C901
    print("=" * 100)
    print("  LE VERDICT — *nos carrys battent-ils un simple VIREMENT dans HLP ?*")
    print("=" * 100)

    # ── 1. LE BENCHMARK, **MESURE** (plus jamais suppose) ──────────────────────────────────────
    print("\n" + "─" * 100)
    print("  1. LE BENCHMARK — le vault HLP, **mesure** (j'avais SUPPOSE « 10 a 30 % »)")
    print("─" * 100)
    try:
        d = asyncio.run(_hlp())
    except Exception as e:  # noqa: BLE001
        print("\n  🔴 `vaultDetails` inaccessible : %s" % e)
        print("     ***ETAT VIDE HONNETE.*** Sans benchmark mesure, **je ne rends aucun verdict.**")
        print("     *Un verdict rendu contre un benchmark invente ne vaut rien.*")
        return 1

    apr_hlp = d.get("apr")
    try:
        apr_hlp = float(apr_hlp)
    except (TypeError, ValueError):
        apr_hlp = None

    print("\n  vault  : %s" % d.get("name", "?"))
    print("  TVL    : %s" % d.get("maxDistributable", "?"))
    if apr_hlp is None:
        print("\n  🔴 champ `apr` absent du payload -> **aucun verdict**. Etat vide honnete.")
        return 1
    print("  🎯 **APR HLP (chiffre de Hyperliquid lui-meme) : %.2f %%**" % (apr_hlp * 100))
    print("\n  🚩 **CE QUE JE NE SAIS PAS, ET QUE JE NE VAIS PAS CACHER :**")
    print("     Ce chiffre est le champ `apr` que HL publie. ***Je ne connais pas la FENETRE")
    print("     exacte qu'il utilise*** (30 j ? depuis le lancement ?). Il peut donc refleter")
    print("     une periode recente defavorable plutot que la vie entiere du vault.")
    print("     -> **le benchmark est MESURE, pas suppose** ; mais sa fenetre reste une")
    print("        inconnue, et je prefere le dire que de faire passer une lecture pour une")
    print("        preuve. *C'est exactement l'erreur qui a produit le faux 38 %% APR.*")

    # Contre-verifie avec l'historique de valeur de compte (drawdown).
    dd_hlp = None
    for periode, bloc in (d.get("portfolio") or []):
        if periode == "allTime" and isinstance(bloc, dict):
            hist = bloc.get("accountValueHistory") or []
            vals = []
            for p in hist:
                try:
                    vals.append(float(p[1]))
                except (IndexError, TypeError, ValueError):
                    continue
            if len(vals) > 2:
                dd_hlp = _drawdown(vals)
    if dd_hlp is not None:
        print("     drawdown max observe sur le solde du vault : **%.1f %%**" % (dd_hlp * 100))
        print("     *(le solde inclut les depots : c'est un indicateur, pas une NAV par part)*")

    print("\n  🚩 **UN HLP GAGNANT NE REFUTE PAS T1b.** Ses privileges, aucun ne nous est accessible :")
    for p in PRIVILEGES:
        print("       - %s" % p)
    print("     *Le market making marche — POUR CELUI QUI EST PAYE POUR LE FAIRE.*")

    # ── 2. NOS CARRYS, au NET (le bug de l'APR brut vient d'etre repare) ───────────────────────
    print("\n" + "─" * 100)
    print("  2. NOS CARRYS — **au NET** (les 23 bps de couts sont enfin DANS le chiffre)")
    print("─" * 100)

    spot = charger_spot_carryables(SPOT)
    par: dict[str, list[float]] = collections.defaultdict(list)
    if FUNDING.exists():
        for ligne in FUNDING.read_text(encoding="utf-8").splitlines():
            try:
                x = json.loads(ligne)
                par[str(x["coin"]).upper()].append(float(x["funding"]) * 1e4)
            except Exception:  # noqa: BLE001
                continue

    print("\n  %-8s %10s %10s %10s %10s   %s"
          % ("coin", "fund/h", "APR brut", "APR net", "net maker", "verdict vs HLP %.1f %%"
             % (apr_hlp * 100)))

    lignes = []
    for c in sorted(spot):
        f = par.get(c, [])
        if len(f) < 720:
            continue
        moy = statistics.fmean(f)
        part = sum(1 for x in f if x > 0) / len(f)
        if moy <= 0 or part < 0.80:
            continue
        cand = CandidatCarry(coin=c, funding_bps_h=moy, notional_usd=500.0)
        brut = cand.apr_brut_sur_capital
        net_t = cand.apr_net_sur_capital(cout_bps=COUT_ALLER_RETOUR_TAKER_BPS)
        net_m = cand.apr_net_sur_capital(cout_bps=COUT_ALLER_RETOUR_MAKER_BPS)

        # 🔴 BUG DE MON PROPRE OUTIL, CORRIGE : MON (APR net = **0,00 %**) etait affiche
        #    « ✅ BAT HLP » -- parce que 0,00 > -0,01. ***Un coin qui ne s'ouvre PAS ne bat
        #    RIEN.*** C'est un faux vainqueur, exactement le genre que ce projet traque.
        #    *Le comparateur doit d'abord demander : est-ce seulement un TRADE ?*
        if not evaluer(cand).ouvrable:
            print("  %-8s %+10.4f %9.2f%% %9s %9s   ⚪ **NON OUVRABLE** — ne peut battre personne"
                  % (c, moy, brut * 100, "-", "-"))
            continue

        bat = net_t > apr_hlp
        v = "✅ **BAT HLP**" if bat else "🔴 **DOMINE PAR HLP** — autant virer l'argent"
        print("  %-8s %+10.4f %9.2f%% %9.2f%% %9.2f%%   %s"
              % (c, moy, brut * 100, net_t * 100, net_m * 100, v))
        lignes.append({"coin": c, "funding_bps_h": round(moy, 4),
                       "apr_brut_pct": round(brut * 100, 2),
                       "apr_net_taker_pct": round(net_t * 100, 2),
                       "apr_net_maker_pct": round(net_m * 100, 2),
                       "bat_hlp": bat})

    # ── 3. LE VERDICT ─────────────────────────────────────────────────────────────────────────
    gagnants = [x for x in lignes if x["bat_hlp"]]
    perdants = [x for x in lignes if not x["bat_hlp"]]

    print("\n" + "=" * 100)
    print("  VERDICT")
    print("=" * 100)

    if not lignes:
        print("\n  ⚪ aucun carry mesurable. **Etat vide honnete.**")
    else:
        print("\n  ✅ battent HLP  : %s"
              % (", ".join("%s (%.2f %%)" % (x["coin"], x["apr_net_taker_pct"])
                           for x in gagnants) if gagnants else "**AUCUN**"))
        print("  🔴 domines      : %s"
              % (", ".join("%s (%.2f %%)" % (x["coin"], x["apr_net_taker_pct"])
                           for x in perdants) if perdants else "aucun"))

    if perdants:
        print("\n  🔴🔴 **CE QU'IL FAUT ENTENDRE :**")
        print("     Ces coins **passent nos portes** — leur edge net est reel et positif.")
        print("     Mais ils rendent **MOINS qu'un depot passif dans HLP**.")
        print("     ***Ce ne sont pas des opportunites. Ce sont des occasions manquees.***")
        print("     *On prendrait un risque de liquidation, un risque d'inversion du funding et")
        print("      un risque de carnet mince... pour gagner MOINS qu'en ne faisant rien.*")

    if not gagnants:
        print("\n  🔴🔴🔴 **AUCUN de nos carrys ne bat HLP.**")
        print("     ***Toute la complexite qu'on a construite est dominee par un VIREMENT.***")
        print("     Je ne vais pas l'habiller. C'est le resultat.")
    else:
        print("\n  ⚠️ **MEME POUR CEUX QUI BATTENT HLP, ce n'est pas une promesse :**")
        print("     - le funding **peut s'inverser** (BERA -0,83 · STABLE -0,99 : ils l'ont fait) ;")
        print("     - la **jambe perp peut etre LIQUIDEE** (X-08) ;")
        print("     - la **profondeur du carnet SPOT n'est pas encore verifiee** :")
        print("       *un edge sur un carnet de 3 $ n'existe pas* ;")
        print("     - HLP porte du risque aussi : comparer les **drawdowns**, pas que les APR.")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({
        "apr_hlp_mesure": apr_hlp,
        "drawdown_hlp": dd_hlp,
        "carrys": lignes,
        "gagnants": [x["coin"] for x in gagnants],
        "domines_par_hlp": [x["coin"] for x in perdants],
        "cout_taker_bps": COUT_ALLER_RETOUR_TAKER_BPS,
        "cout_maker_bps": COUT_ALLER_RETOUR_MAKER_BPS,
        "note": ("L'APR affiche etait le BRUT : les 23 bps de couts etaient verifies a la porte "
                 "mais jamais soustraits du chiffre. Corrige le 2026-07-14."),
        "paper_only": True, "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % SORTIE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
