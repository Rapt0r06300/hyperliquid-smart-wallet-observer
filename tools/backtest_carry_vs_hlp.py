"""LE CARRY, REJOUÉ EN PAPER — **et jugé par le CASH, le BUY-AND-HOLD et HLP.**

═══════════════════════════════════════════════════════════════════════════════════════════════
LA RÈGLE DE CE FICHIER
═══════════════════════════════════════════════════════════════════════════════════════════════

    ***Une stratégie qui ne bat pas un dépôt passif n'est pas une stratégie : c'est un hobby.***

On rejoue le carry sur des **mois** de `fundingHistory` (endpoint public — celui qu'on avait
sous les yeux pendant que X-04 se contentait de 18,9 h), et on le confronte **immédiatement**
à ses trois juges :

  1. **LE CASH** — 0 % de rendement, 0 % de drawdown. *Toute stratégie à rendement négatif est
     dominée par ne rien faire, sur les DEUX dimensions.*
  2. **LE BUY-AND-HOLD** — acheter HYPE et ne plus y toucher. Aucun frais, aucun spread.
  3. **LE VAULT HLP** — un virement chez le market maker officiel de Hyperliquid.

⚠️ **Aucun chiffre n'est promis.** Si le carry perd, on l'écrit. Si HLP le bat, on l'écrit.
*On ne maquille pas : on soustrait.*

Lecture seule. Aucun ordre réel. Paper-only.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.honest_metrics import (  # noqa: E402
    buy_and_hold,
    comparer_au_buy_and_hold,
)
from hl_observer.collection.funding_backfill import (  # noqa: E402
    PointFunding,
    couverture,
    parser_funding,
)
from hl_observer.strategies.carry_runtime import (  # noqa: E402
    CAPITAL_SUR_DEUX_JAMBES,
    COUT_ALLER_RETOUR_TAKER_BPS,
    CandidatCarry,
    evaluer,
)

FUNDING = RACINE / "runtime" / "history" / "funding.jsonl"
BOUGIES = RACINE / "runtime" / "history" / "candles_1h.jsonl"
SORTIE = RACINE / "data" / "reports" / "carry_vs_hlp.json"

CAPITAL = 1000.0          # capital paper, réparti sur les DEUX jambes

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔴🔴 LA CONTRAINTE QUI DÉCIDE DE TOUT — et qu'on peut oublier en regardant le funding.
#
#     ***LE CARRY EXIGE UNE JAMBE SPOT.*** Sans elle, on n'est PAS delta-neutre :
#     on est **short le perp À NU**, c'est-à-dire un PARI DIRECTIONNEL déguisé en carry.
#
# Or Hyperliquid n'a du **spot** que sur très peu de marchés. BTC, ETH, SOL, NEAR… sont des
# **perps SANS spot HL**. Y « faire du carry » est impossible.
#
# 🎯 C'est EXACTEMENT ce que T2 avait trouvé : **7 des 8 candidats sont morts.** Seul HYPE
#    a survécu — et la raison n'était pas le funding, **c'était l'existence du spot.**
#
# ⚠️ Cette liste est une **hypothèse minimale et prudente**. Un coin absent est traité comme
#    NON-CARRYABLE. *On refuse par défaut : un carry sans spot est un mensonge.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
MOTIF_PAS_DE_SPOT = "PAS_DE_MARCHE_SPOT_HL_UN_CARRY_SANS_SPOT_EST_UN_SHORT_PERP_A_NU"

# 🔴 CORRIGE LE 2026-07-14 : je SUPPOSAIS `{"HYPE", "PURR"}` — **de mémoire, jamais vérifié.**
# *La même erreur que « data-limited » et « pas de source historique » : deviner au lieu de
#  demander.* -> on lit maintenant la VRAIE liste, produite par `tools/lister_spot_hl.py`
#  depuis l'endpoint public `spotMeta`.
SPOT_JSON = RACINE / "data" / "reports" / "spot_hl.json"


def _spot_hl() -> set[str]:
    """La liste RÉELLE. Si le fichier n'existe pas, **on ne devine pas : on le dit.**"""
    if not SPOT_JSON.exists():
        return set()
    try:
        d = json.loads(SPOT_JSON.read_text(encoding="utf-8"))
        return {str(c).upper() for c in d.get("carryables", [])}
    except Exception:  # noqa: BLE001
        return set()


def _charger_funding() -> dict[str, list[PointFunding]]:
    """🔴 BUG TROUVE PAR LE PREMIER RUN REEL (2026-07-14) :

    Le backfill ecrit `{"coin","time","funding","premium"}` (via `PointFunding.as_dict()`),
    mais `parser_funding` attend la cle **`fundingRate`** (le format de l'API).
    -> le lecteur trouvait **0 point** et annoncait « aucun historique ».

    ***Un lecteur qui ne reconnait pas son propre format est un lecteur qui ment par omission.***
    (Et il l'a fait honnetement : « etat vide honnete » -- **au lieu de fabriquer un chiffre**.)

    On lit maintenant le format du SPOOL, pas celui de l'API. Deny-by-default conserve :
    une ligne illisible est SAUTEE, jamais devinee.
    """
    if not FUNDING.exists():
        return {}
    par: dict[str, list[PointFunding]] = collections.defaultdict(list)
    for ligne in FUNDING.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ligne)
            coin = str(d["coin"]).strip().upper()
            t = int(d["time"])
            f = float(d["funding"])          # <- le format du SPOOL (pas `fundingRate`)
        except Exception:  # noqa: BLE001
            continue
        if coin and t > 0:
            par[coin].append(PointFunding(coin=coin, time_ms=t, funding=f))
    for c in par:
        par[c].sort(key=lambda p: p.time_ms)
    return par


def _charger_prix() -> dict[str, list[tuple[int, float]]]:
    if not BOUGIES.exists():
        return {}
    par: dict[str, list[tuple[int, float]]] = collections.defaultdict(list)
    for ligne in BOUGIES.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ligne)
            par[d["coin"]].append((int(d["t_ms"]), float(d["c"])))
        except Exception:  # noqa: BLE001
            continue
    for c in par:
        par[c].sort()
    return par


def rejouer_carry(points: list[PointFunding], *, capital: float = CAPITAL) -> dict:
    """Paper : on est SHORT le perp / LONG le spot. On encaisse le funding, **heure par heure**.

    🔴 Les coûts (4 exécutions, **23 bps** — pas 18 : le spot coûte 2,7× le perp en maker)
    sont payés **une fois**, à l'ouverture. *On ne les oublie pas, et on ne les double pas.*
    """
    if len(points) < 24:
        return {"suffisant": False, "motif": "moins de 24 h de funding"}

    notional = capital / CAPITAL_SUR_DEUX_JAMBES     # la moitié sur chaque jambe
    equity = [capital - notional * COUT_ALLER_RETOUR_TAKER_BPS / 1e4]   # coûts d'entrée
    for p in points:
        # SHORT le perp -> on encaisse quand le funding est POSITIF.
        gain = notional * (p.funding / 1.0)
        equity.append(equity[-1] + gain)

    heures = len(points)
    rendement = equity[-1] / capital - 1.0
    apr = ((1.0 + rendement) ** (8760.0 / heures) - 1.0) if heures > 0 else 0.0
    return {
        "suffisant": True, "heures": heures, "jours": round(heures / 24.0, 1),
        "equity": equity, "rendement": rendement, "apr": apr,
        "cout_entree_bps": COUT_ALLER_RETOUR_TAKER_BPS,
    }


def main() -> int:
    print("=" * 96)
    print("  LE CARRY, REJOUÉ EN PAPER — et jugé par le CASH, le BUY-AND-HOLD et HLP")
    print("=" * 96)

    fundings = _charger_funding()
    prix = _charger_prix()
    SPOT_HL = _spot_hl()

    if not SPOT_HL:
        print("\n  ⚠️ **La liste des marchés SPOT n'a pas été récupérée.**")
        print("     Lancer `tools/lister_spot_hl.py` d'abord (endpoint public `spotMeta`).")
        print("     *Je ne DEVINE pas la liste : c'est l'erreur qui m'a fait déclarer")
        print("      « data-limited » ce qui était à un appel de distance.*")
        return 1

    if not fundings:
        print("\n  🔴 **AUCUN historique de funding.** Lancer d'abord `BACKFILL-CANDLES.cmd`")
        print("     puis `tools/backfill_funding.py --jours=120`.")
        print("     *État vide honnête : on ne fabrique pas de chiffre.*")
        return 1

    resultats = []
    print("\n  %-7s %7s %9s %11s %11s %11s   %s"
          % ("coin", "jours", "fund/h", "CARRY apr", "B&H apr", "CASH", "verdict"))
    print("  " + "-" * 88)

    for coin, pts in sorted(fundings.items()):
        r = rejouer_carry(pts)
        if not r.get("suffisant"):
            continue
        moy = sum(p.bps_h for p in pts) / len(pts)

        # le juge n°2 : le buy-and-hold sur le même coin
        px = [p for _, p in prix.get(coin, [])]
        r_bh, dd_bh = buy_and_hold(px) if px else (0.0, 0.0)
        c = comparer_au_buy_and_hold(r["equity"], px) if px else None

        # 🔴 LA PORTE N°0 : y a-t-il seulement un marché SPOT ?
        # *Sans spot, on n'est pas delta-neutre : on est short le perp À NU.*
        a_du_spot = coin in SPOT_HL
        v = evaluer(CandidatCarry(coin=coin, funding_bps_h=moy, notional_usd=500.0))
        ouvrable = a_du_spot and v.ouvrable and r["apr"] > 0

        if not a_du_spot:
            verdict = "🔴 PAS DE SPOT HL"
        elif r["apr"] <= 0:
            verdict = "🔴 DOMINÉ PAR LE CASH"
        elif not v.ouvrable:
            verdict = "⚠️ funding trop faible"
        else:
            verdict = "✅ OUVRABLE"

        print("  %-7s %7.1f %+9.4f %+10.2f%% %+10.2f%% %10s   %s"
              % (coin, r["jours"], moy, r["apr"] * 100, r_bh * 100, "0.00%", verdict))

        resultats.append({
            "coin": coin, "jours": r["jours"], "funding_moyen_bps_h": round(moy, 4),
            "carry_apr_pct": round(r["apr"] * 100, 2),
            "buy_and_hold_apr_pct": round(r_bh * 100, 2),
            "cash_apr_pct": 0.0,
            "a_du_spot_HL": a_du_spot,
            "ouvrable": ouvrable,
            "motif": v.motif if a_du_spot else MOTIF_PAS_DE_SPOT,
            "domine_par_le_cash": (r["apr"] <= 0),
            "bat_le_buy_and_hold": (c.bat_le_rendement if c else None),
            "paper_only": True, "real_execution": False,
        })

    if not resultats:
        print("\n  Aucun coin avec assez d'historique. **État vide honnête.**")
        return 1

    ouvrables = [x for x in resultats if x["ouvrable"]]
    sans_spot = [x for x in resultats if not x["a_du_spot_HL"]]

    print("\n" + "=" * 96)
    print("  LA PORTE N°0 — **LE SPOT**")
    print("=" * 96)
    print("\n  🔴 **%d/%d coins n'ont PAS de marché SPOT sur Hyperliquid.**"
          % (len(sans_spot), len(resultats)))
    print("     *Sans spot, on n'est PAS delta-neutre : on est **short le perp À NU**.*")
    print("     ***Un carry sans spot n'est pas un carry : c'est un pari directionnel déguisé.***")
    print("\n  🎯 C'est EXACTEMENT ce que T2 avait trouvé : **7 des 8 candidats sont morts.**")
    print("     Et la raison n'était pas le funding — **c'était l'existence du spot.**")

    print("\n" + "=" * 96)
    print("  LES TROIS JUGES")
    print("=" * 96)
    print("\n  1️⃣  LE CASH (0 %% de rendement, 0 %% de drawdown)")
    domines = [x for x in resultats if x["domine_par_le_cash"]]
    print("      %d/%d coins sont **DOMINÉS PAR LE CASH** (rendement <= 0)."
          % (len(domines), len(resultats)))

    print("\n  2️⃣  LE BUY-AND-HOLD")
    battus = [x for x in resultats if x.get("bat_le_buy_and_hold")]
    print("      le carry bat le B&H sur **%d/%d** coins." % (len(battus), len(resultats)))

    print("\n  3️⃣  LE VAULT HLP — 🎯 **LE JUGE QUI COMPTE**")
    print("      HLP **EST** le market maker de Hyperliquid. Il **encaisse une part des frais**")
    print("      du protocole et il **EST le liquidateur**. C'est un virement, pas une stratégie.")
    if ouvrables:
        best = max(ouvrables, key=lambda x: x["carry_apr_pct"])
        print("      Notre meilleur carry : **%s à %+.2f %% APR**."
              % (best["coin"], best["carry_apr_pct"]))
        print("      ⚠️ **Lancer `MESURER-3-PISTES.cmd` pour obtenir l'APR réel de HLP.**")
        print("         *S'il le bat, toute notre complexité est dominée par un dépôt passif —")
        print("          et il faudra le dire.*")
    else:
        print("      🔴 **AUCUN carry ouvrable.** Il n'y a rien à comparer : le cash gagne.")

    print("\n" + "-" * 96)
    print("  ⚠️ **Aucun chiffre n'est promis.** Ce sont des fundings OBSERVÉS — ils peuvent")
    print("     s'inverser. Et la jambe PERP peut être LIQUIDÉE (X-08).")
    print("     *Une stratégie qui ne tient que sur un actif n'est pas une stratégie.*")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({
        "capital_paper": CAPITAL,
        "cout_aller_retour_bps": COUT_ALLER_RETOUR_TAKER_BPS,
        "coins": resultats,
        "n_ouvrables": len(ouvrables),
        "n_domines_par_le_cash": len(domines),
        "paper_only": True, "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % SORTIE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
