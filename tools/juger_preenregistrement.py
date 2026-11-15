#!/usr/bin/env python3
"""JUGE le protocole gele dans `docs/PREENREGISTREMENT_5USD.md` — une fois, sans ajustement.

A lancer le 19/11, apres la fin de la campagne. Toute la configuration est **codee en dur ici**
exactement comme elle a ete gelee le 14/11, AVANT tout regard sur la fenetre de campagne. Aucune
option de ligne de commande ne permet de la changer : c'est volontaire. Un outil qui laisserait
regler `k` ou l'horizon apres avoir vu le resultat transformerait le jugement en recherche, et
c'est precisement le mecanisme qui produit un PBO de 0,81.

L'outil verifie aussi l'empreinte du protocole : si le document a ete modifie depuis le gel, il
REFUSE de juger plutot que de valider un protocole reecrit apres coup.

PAPER / lecture seule.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import statistics
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

PROTOCOLE = Path("docs") / "PREENREGISTREMENT_5USD_V2.md"
#: Empreinte du protocole au moment du gel (14/11/2026). Ne jamais la mettre a jour « pour que ca
#: passe » : si elle ne correspond plus, c'est le protocole qui a change, donc le jugement est nul.
#: Empreinte de la v2 au gel (14/11/2026), calendrier des verdicts inclus. L amendement du
#: calendrier a ete ecrit AVANT qu une seule fenetre de jugement n existe : il ne change aucun
#: parametre, il declare quand regarder. Ne JAMAIS mettre cette valeur a jour « pour que ca passe ».
EMPREINTE_GELEE = "f42302daa601849273864e86f80fde4d"

# --- configuration GELEE. Aucune de ces valeurs n'est reglable depuis la ligne de commande.
SIGNAL = "funding_brut"
INVERSER = True
K = 3
#: v2 : le portefeuille porte CINQ horizons. 336 h commande la date du verdict complet.
HORIZONS = (24, 48, 96, 168, 336)
DETENTION_H = 96
FENETRE_H = 96
TRANCHES = 8
PAS_H = 12
COUVERTURE = 1.0
PONDERATION = "egale"
MMR = 0.05
FACTEUR = 4.0
COUT_TAKER = 2 * (4.5 + 4.36) / 1e4
COUT_MAKER = 2 * (1.5 - 0.69 + 2.16) / 1e4
CAPITAL = 350.0
CIBLE_USD_JOUR = 5.0

#: Attentes ecrites D'AVANCE (facteur 4). Les reproduire ici permet de comparer le resultat a ce
#: qui etait predit, et non a ce qu'on aurait aime.
#: v2 — attentes du portefeuille MULTI-HORIZONS (taker mesure, facteur 4), ecrites d avance.
ATTENDU = {"pire tiers": 3.78, "hors echantillon": 4.56, "meilleur tiers": 5.19}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--depuis", required=True,
                   help="debut de la fenetre de jugement, AAAA-MM-JJ (ex. 2026-11-13)")
    args = p.parse_args(argv)
    root = Path(args.root)

    doc = root / PROTOCOLE
    if not doc.is_file():
        print(f"[juge] protocole absent : {doc}")
        return 2
    empreinte = hashlib.sha256(doc.read_text(encoding="utf-8").encode("utf-8")).hexdigest()[:32]
    if empreinte != EMPREINTE_GELEE:
        print("[juge] REFUS DE JUGER : le protocole a ete MODIFIE depuis le gel.")
        print(f"       attendu {EMPREINTE_GELEE}, trouve {empreinte}")
        print("       Un protocole reecrit apres coup ne prouve rien. Restaurer, ou declarer")
        print("       explicitement qu'il s'agit d'un NOUVEAU protocole a juger sur une AUTRE")
        print("       fenetre encore jamais regardee.")
        return 3

    import datetime as dt
    # On importe les constantes de cout depuis l'outil OFFICIEL plutot que de les redefinir ici :
    # deux definitions du meme cout finiraient par divulguer, et le juge annoncerait un chiffre que
    # l'outil de mesure ne reproduirait pas.
    from mesurer_strategie import (series_par_horizon, juger_multi, charger_funding,
                                   charger_prix, slippage_bps, FUNDING, BOUGIES,
                                   TRANCHES as TR, TAKER_BPS)

    debut_h = int(dt.datetime.strptime(args.depuis, "%Y-%m-%d")
                  .replace(tzinfo=dt.timezone.utc).timestamp()) // 3600

    funding = charger_funding(root / FUNDING)
    prix = charger_prix(root / BOUGIES)
    if not funding or not prix:
        print("[juge] donnees absentes.")
        return 2
    slip, source = slippage_bps(root)
    cout = 2 * (TAKER_BPS + slip) / 1e4

    print("JUGEMENT DU PROTOCOLE PREENREGISTRE v2")
    print("=" * 78)
    print(f"  empreinte verifiee : {empreinte}")
    print(f"  configuration gelee : k={K}, horizons {HORIZONS}, {TR} tranches (/{PAS_H} h), "
          f"couverture 100 %, facteur {FACTEUR:.0f}")
    print(f"  cout : taker {cout*1e4:.1f} bps/jambe (slippage {slip:.2f} b, {source})")
    print(f"  univers : {len(funding)} coins de funding")
    print(f"  fenetre de jugement : decisions a partir du {args.depuis}")
    print()

    series = series_par_horizon(funding, prix, cout=cout)
    # --- VERDICTS PARTIELS, horizon par horizon, selon le calendrier preenregistre
    print("  VERDICTS PARTIELS (rapportes, JAMAIS utilises pour re-choisir)")
    print(f"  {'horizon':>8}{'fenetres':>10}{'etat':>14}   lecture")
    prets: list[int] = []
    for horizon in HORIZONS:
        fenetres = [t for t in series.get(horizon, {}) if t >= debut_h]
        pret = len(fenetres) >= TR
        if pret:
            prets.append(horizon)
        print(f"  {horizon:>7}h{len(fenetres):>10}{'JUGEABLE' if pret else 'pas encore':>14}"
              + ("" if pret else f"   il en faut {TR}"))
    print()
    print("  Un horizon seul porte un repli bien plus eleve que le portefeuille (6,35 % pour le")
    print("  96 h contre 2,79 % pour les cinq), donc moins de levier et moins de USD/jour : un")
    print("  partiel faible n'infirme PAS le portefeuille complet, et un partiel fort ne le")
    print("  confirme pas.")
    print()

    # --- LE VERDICT COMPLET : seulement si TOUS les horizons sont jugeables
    if len(prets) < len(HORIZONS):
        manquants = [h for h in HORIZONS if h not in prets]
        print(f"  PORTEFEUILLE COMPLET : **PAS ENCORE JUGEABLE** — manque(nt) "
              f"{', '.join(str(h) + 'h' for h in manquants)}.")
        print(f"  Le plus long ({max(HORIZONS)} h) commande la date : 8e decision + "
              f"{max(HORIZONS)/24:.0f} jours de detention.")
        return 0
    complet = juger_multi(series, capital=CAPITAL, facteur=FACTEUR)
    juge = juger_multi(series, capital=CAPITAL, facteur=FACTEUR, debut=debut_h,
                       repli_impose=complet["repli"] if complet else None)
    if not juge:
        print("  PORTEFEUILLE COMPLET : non jugeable malgre des horizons prets.")
        return 0
    print(f"  PORTEFEUILLE COMPLET — {juge['n']} instants")
    print(f"  brut {juge['brut']*100:+.1f} %/an | repli {juge['repli']*100:.2f} % "
          f"(de TOUTE l'histoire) | levier {juge['levier']:.2f}x")
    print(f"  **{juge['usd_jour']:+.2f} USD/jour** (cible {CIBLE_USD_JOUR:.2f}) -> "
          f"{'CIBLE TENUE' if juge['usd_jour'] >= CIBLE_USD_JOUR else 'cible NON tenue'}")
    print(f"  liquidation si le livre perd {juge['liquide_si']:.1%}")
    print()
    print("  face aux attentes ecrites d'avance (taker, facteur 4) :")
    for nom, valeur in (("pire tiers", 3.78), ("hors echantillon", 4.56),
                        ("meilleur tiers", 5.19)):
        print(f"    {nom:<20}attendu {valeur:+.2f} -> ecart {juge['usd_jour'] - valeur:+.2f}")
    print()
    print("  Rappel : aucun parametre n'est reglable ici. Si le resultat decoit, le resultat")
    print("  decoit — c'est tout l'interet d'avoir gele le protocole avant de regarder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
