#!/usr/bin/env python3
"""T2b / #588 — LE CARRY HYPE SURVIT-IL A SON PROPRE MARCHE ?

T2 a trouve le seul resultat positif du projet : LONG spot HYPE + SHORT perp HYPE, +33,6 bps nets
dans son PIRE mois sur 90 jours de funding REEL (~7 % APR). Mais T2 a compte le funding, les frais,
le spread et la base... et PAS la liquidation de la jambe perp.

    Le gain de la jambe spot est en HYPE, pas en USDC. Il ne recharge PAS la marge du short.
    Si le prix monte assez, le compte perp est liquide -- pendant que le portefeuille, lui, est
    parfaitement neutre.

CE SCRIPT MESURE, SUR DES PRIX REELS :
  1. le levier max de HYPE (donc sa marge de maintenance) ;
  2. la PIRE hausse reellement subie sur chaque duree de detention (24 h, 7 j, 30 j) ;
  3. pour chaque taille de marge : liquidation ou pas, et le rendement une fois le CAPITAL TOTAL
     (spot paye cash + marge du perp) compte -- ce que T2 n'avait pas fait.

    python tools/mesurer_risque_liquidation_carry.py

LECTURE SEULE. Endpoint /info public. Aucune cle, aucune signature, aucun ordre. JAMAIS.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.funding.carry_liquidation_risk import (  # noqa: E402
    evaluer_risque_liquidation,
    fraction_marge_maintenance,
    marge_requise_pour_survivre,
    mouvement_adverse_de_liquidation,
    pire_hausse_sur_fenetre,
    rendement_sur_capital_total,
)

API = "https://api.hyperliquid.xyz/info"
COIN = "HYPE"

# Le chiffre de T2 : +33,6 bps nets sur 30 jours, dans le PIRE mois des 90 jours mesures.
RENDEMENT_T2_BPS_30J = 33.6
NOTIONNEL_USD = 500.0

# Les durees de detention plausibles pour un carry.
FENETRES_H = {"24 h": 24, "7 jours": 24 * 7, "30 jours": 24 * 30}

# Les tailles de marge a tester : m = marge / notionnel du perp.
GRILLE_MARGE = (0.15, 0.25, 0.35, 0.50, 0.75, 1.00, 1.50)


def _post(payload: dict):
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=25.0) as r:
        return json.loads(r.read().decode("utf-8"))


def _levier_max(coin: str) -> float | None:
    meta = _post({"type": "meta"})
    for a in meta.get("universe") or []:
        if str(a.get("name") or "").upper() == coin.upper():
            lv = a.get("maxLeverage")
            return float(lv) if lv else None
    return None


def _bougies_1h(coin: str, heures: int) -> list[float]:
    """Les CLOTURES horaires. On demande par tranches : l'API plafonne a 5000 bougies."""
    fin = int(time.time() * 1000)
    debut = fin - heures * 3600 * 1000
    payload = {"type": "candleSnapshot",
               "req": {"coin": coin.upper(), "interval": "1h",
                       "startTime": debut, "endTime": fin}}
    data = _post(payload) or []
    out: list[float] = []
    for c in data:
        try:
            out.append(float(c["c"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def main() -> int:
    print("\n" + "=" * 78)
    print("  T2b / #588 -- LA JAMBE PERP DU CARRY %s PEUT-ELLE ETRE LIQUIDEE ?" % COIN)
    print("=" * 78)

    try:
        lev = _levier_max(COIN)
        prix = _bougies_1h(COIN, 24 * 200)          # ~200 jours d'histoire horaire
    except Exception as exc:                        # noqa: BLE001
        print("\n  ECHEC RESEAU : %s" % exc)
        print("  Aucune donnee -> AUCUNE conclusion. (INSUFFICIENT_DATA)\n")
        return 3

    if not lev or len(prix) < 24 * 40:
        print("\n  Donnee insuffisante (levier=%s, %d bougies) -> INSUFFICIENT_DATA.\n"
              % (lev, len(prix)))
        return 3

    mm = fraction_marge_maintenance(lev)
    print("\n  Levier max %s          : %.0fx" % (COIN, lev))
    print("  Marge de maintenance    : %.2f %%   (doc : moitie de la marge initiale au levier max)"
          % (mm * 100.0))
    print("  Historique horaire      : %d bougies (~%.0f jours)" % (len(prix), len(prix) / 24.0))
    print("  Prix : min %.3f  max %.3f  dernier %.3f" % (min(prix), max(prix), prix[-1]))

    # --- 1. LA PIRE HAUSSE REELLEMENT SUBIE, PAR DUREE DE DETENTION
    print("\n  --- LA PIRE HAUSSE REELLEMENT SUBIE (toutes les entrees possibles, causal)")
    pires: dict[str, float] = {}
    for nom, f in FENETRES_H.items():
        if len(prix) <= f:
            continue
        p = pire_hausse_sur_fenetre(prix, f)
        pires[nom] = p
        print("      detention %-9s -> pire hausse subie par le SHORT : +%6.1f %%"
              % (nom, p * 100.0))

    if "30 jours" not in pires:
        print("\n  Pas assez d'historique pour une detention de 30 jours -> INSUFFICIENT_DATA.\n")
        return 3

    pire_30j = pires["30 jours"]
    m_requis = marge_requise_pour_survivre(pire_30j, mm)

    # --- 2. LA GRILLE : TAMPON vs RENDEMENT
    print("\n  --- LE CHOIX QU'ON NE PEUT PAS ESQUIVER (detention 30 j, pire hausse +%.1f %%)"
          % (pire_30j * 100.0))
    print("      %-8s %-14s %-10s %-16s %-18s" %
          ("marge m", "liquide a", "survit ?", "rendement brut", "rendement REEL"))
    print("      %-8s %-14s %-10s %-16s %-18s" %
          ("(M/N)", "(hausse)", "(30 j)", "(sur N)", "(sur N + M)"))
    print("      " + "-" * 70)
    for m in GRILLE_MARGE:
        r_liq = mouvement_adverse_de_liquidation(m, mm)
        rdt = rendement_sur_capital_total(RENDEMENT_T2_BPS_30J, m)
        survit = r_liq > pire_30j
        print("      %-8.2f %-14s %-10s %-16s %-18s"
              % (m,
                 ("+%.1f %%" % (r_liq * 100.0)) if r_liq > 0 else "DEJA LIQUIDE",
                 "OUI" if survit else "NON",
                 "%.1f bps" % RENDEMENT_T2_BPS_30J,
                 "%.1f bps%s" % (rdt, "" if survit else "   <- jamais encaisse")))

    # --- 3. LE VERDICT, AU POINT DE SURVIE MINIMAL
    v = evaluer_risque_liquidation(
        coin=COIN, levier_max=lev, marge_ratio=m_requis,
        pire_mouvement_observe=pire_30j, rendement_brut_bps=RENDEMENT_T2_BPS_30J,
        notionnel_usd=NOTIONNEL_USD,
    )
    apr_brut = RENDEMENT_T2_BPS_30J / 10_000.0 * 12.0 * 100.0
    apr_reel = v.rendement_sur_capital_bps / 10_000.0 * 12.0 * 100.0

    print("\n" + "=" * 78)
    print("  VERDICT")
    print("=" * 78)
    # 🚩 %.2f, PAS %.0f : mon 1er rapport affichait « 105 % », j'ai recopie CET ARRONDI dans un
    # test... et la jambe etait liquidee (105,00 % < 105,38 % requis). Un rapport arrondi n'est pas
    # une entree de calcul.
    print("\n  Pour SURVIVRE a la pire hausse reellement observee sur 30 jours (+%.1f %%),"
          % (pire_30j * 100.0))
    print("  il faut une marge de %.2f %% du notionnel du perp." % (m_requis * 100.0))
    print("\n  Capital immobilise pour un carry de %.0f $ de notionnel :" % NOTIONNEL_USD)
    print("      spot (paye CASH, aucun levier) : %8.2f $" % NOTIONNEL_USD)
    print("      marge du perp                  : %8.2f $" % (m_requis * NOTIONNEL_USD))
    print("      -------------------------------------------")
    print("      CAPITAL TOTAL                  : %8.2f $" % ((1.0 + m_requis) * NOTIONNEL_USD))
    print("\n  Rendement annonce par T2 (sur le notionnel seul) : %.1f bps / 30 j  (~%.1f %% APR)"
          % (RENDEMENT_T2_BPS_30J, apr_brut))
    print("  Rendement REEL   (sur le capital TOTAL)          : %.1f bps / 30 j  (~%.1f %% APR)"
          % (v.rendement_sur_capital_bps, apr_reel))
    print("\n  En cas de BACKSTOP (equity < 2/3 de la maintenance), la marge de maintenance est")
    print("  CONFISQUEE (doc officielle) : perte seche de %.2f $ sur %.0f $ de notionnel."
          % (v.perte_seche_backstop_usd, NOTIONNEL_USD))
    print("\n  Et surtout : une jambe perp liquidee = plus de couverture = LONG SPOT SEC,")
    print("  c'est-a-dire la zone morte FUNDING_JAMBE_NUE, deja mesuree et deja enterree.")
    print("\n  motif : %s" % v.motif)
    print("  %s\n" % v.note)

    dest = ROOT / "data" / "reports" / "carry_liquidation_588.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({
        "coin": COIN, "levier_max": lev, "marge_maintenance_pct": mm * 100.0,
        "bougies": len(prix),
        "pires_hausses_pct": {k: v2 * 100.0 for k, v2 in pires.items()},
        "marge_requise_30j": m_requis,
        "apr_brut_pct": apr_brut, "apr_reel_pct": apr_reel,
        "verdict": v.as_dict(),
        "real_execution": False,
    }, indent=2), encoding="utf-8")
    print("  -> %s\n" % dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
