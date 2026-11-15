#!/usr/bin/env python3
"""La regle patiente, mesuree sur les 211 jours de funding du coffre. Le chiffre, quel qu'il soit.

Charge `funding_history` du coffre certifie (90 coins, pas horaire), applique la politique de
`carry_patient` avec ses conventions fixees d'avance, et passe le resultat par les portes de
survie (`survie_position`) et d'horizon (`carry_horizon`).

TIER. Ces shards portent `tier: LOCAL` et `reconciliation_status: LOCAL_UNRECONCILED`. C'est le
pont LOCAL, pas le corpus SAFE reconcilie : le chiffre est donc une MESURE SUR DONNEES LOCALES, et
cet outil le dit en tete de sortie plutot que de laisser croire a une certification cloud.

PAPER / lecture seule.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))

SHARDS = Path("runtime") / "coffre_certifie" / "local" / "shards"
DOSSIER = SHARDS / "funding_history"
BOUGIES = SHARDS / "candle"

TAKER_BPS = 4.5
SLIPPAGE_BPS = 2.0


def charger(dossier: Path) -> tuple[dict[str, dict[int, float]], set[str]]:
    """Funding par coin et par heure. Rend aussi les tiers rencontres, pour les declarer."""
    par_coin: dict[str, dict[int, float]] = defaultdict(dict)
    tiers: set[str] = set()
    if not dossier.is_dir():
        return par_coin, tiers
    for fichier in sorted(dossier.glob("*.jsonl.gz")):
        try:
            with gzip.open(fichier, "rt", encoding="utf-8", errors="replace") as flux:
                for ligne in flux:
                    texte = ligne.strip()
                    if not texte.startswith("{"):
                        continue
                    try:
                        objet = json.loads(texte)
                    except ValueError:
                        continue
                    coin = objet.get("coin")
                    instant = objet.get("ts_ms") or objet.get("time")
                    taux = objet.get("funding")
                    if not coin or instant is None or taux is None:
                        continue
                    try:
                        par_coin[str(coin)][int(instant) // 3_600_000] = float(taux)
                    except (TypeError, ValueError):
                        continue
                    if objet.get("tier"):
                        tiers.add(str(objet["tier"]))
        except OSError:
            continue
    return par_coin, tiers


def charger_prix(dossier: Path) -> dict[str, dict[int, float]]:
    """Cloture horaire par coin. On ne prend QUE l'intervalle 1h : melanger des pas differents
    ferait coexister deux definitions de « la cloture de cette heure »."""
    par_coin: dict[str, dict[int, float]] = defaultdict(dict)
    if not dossier.is_dir():
        return par_coin
    for fichier in sorted(dossier.glob("*.jsonl.gz")):
        try:
            with gzip.open(fichier, "rt", encoding="utf-8", errors="replace") as flux:
                for ligne in flux:
                    texte = ligne.strip()
                    if not texte.startswith("{"):
                        continue
                    try:
                        objet = json.loads(texte)
                    except ValueError:
                        continue
                    if objet.get("interval") != "1h":
                        continue
                    coin = objet.get("coin")
                    instant = objet.get("open_ts_ms")
                    cloture = objet.get("close")
                    if not coin or instant is None or cloture is None:
                        continue
                    try:
                        par_coin[str(coin)][int(instant) // 3_600_000] = float(cloture)
                    except (TypeError, ValueError):
                        continue
        except OSError:
            continue
    return par_coin


def main(argv: list[str] | None = None) -> int:
    # 14/11/2026 — OUTIL PERIME, remplace par `tools/mesurer_strategie.py`.
    # Il a servi a REFUTER le carry de funding (-41,3 %/an une fois le prix compte) et c'est a ce
    # titre qu'on garde son code lisible : une refutation doit pouvoir etre reverifiee. Mais ses
    # conventions ont ete depassees le jour meme :
    #   * detention 720 h et k=5 -> 720 h est le PIRE point du plateau rentable (+32,4 % contre
    #     +64,6 % a 96 h), et k=3 s'est revele le plus stable des trois tiers ;
    #   * slippage SUPPOSE a 2 bps -> mesure a ~4,2 bps sur 60 000 carnets (15 % du net) ;
    #   * entree UNIQUE -> le decoupage en 8 tranches vaut un facteur 2,4, a rendement inchange ;
    #   * aucun dimensionnement en marge croisee.
    # Le laisser tourner ferait CONTREDIRE le protocole gele par le depot lui-meme : quiconque
    # lancerait cet outil obtiendrait un autre chiffre que docs/PREENREGISTREMENT_5USD.md.
    print("[carry-patient] OUTIL PERIME -> utiliser tools/mesurer_strategie.py", flush=True)
    print("  raisons : detention 720 h (pire point du plateau), k=5, slippage SUPPOSE a 2 bps",
          flush=True)
    print("  (mesure ~4,2), entree unique (le decoupage vaut x2,4), aucune marge croisee.",
          flush=True)
    return 3


def _ancien_main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--capital", type=float, default=350.0)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    from hl_observer.backtesting import carry_patient as C
    from hl_observer.backtesting import survie_position as S

    funding, tiers = charger(Path(args.root) / DOSSIER)
    if not funding:
        print("[carry] aucun funding lu dans le coffre.")
        return 2

    heures = sorted({h for s in funding.values() for h in s})
    # Cout par JAMBE et par aller-retour : ouverture + fermeture, taker, plus le slippage.
    cout = 2 * (TAKER_BPS + SLIPPAGE_BPS) / 10_000.0

    prix = charger_prix(Path(args.root) / BOUGIES)
    principal = C.mesurer(funding, cout_aller_retour=cout, prix=prix)
    balayage = C.balayage_sans_selection(funding, cout_aller_retour=cout, ks=[2, 3, 5, 8, 12],
                                         prix=prix)
    sans_prix = C.mesurer(funding, cout_aller_retour=cout)

    if args.json:
        print(json.dumps({"principal": principal, "balayage": balayage},
                         ensure_ascii=False, indent=1, default=str))
        return 0

    print("LA REGLE PATIENTE, MESUREE SUR LE FUNDING REEL DU COFFRE")
    print("=" * 76)
    print(f"  tier des donnees : {', '.join(sorted(tiers)) or 'inconnu'} "
          "-> pont LOCAL, pas corpus SAFE reconcilie")
    print(f"  {len(funding)} coins de funding | {len(prix)} coins de prix 1h "
          f"| {len(heures)} heures ({len(heures)/24:.0f} jours)")
    print(f"  conventions FIXEES D'AVANCE : horloge {C.HORLOGE_H} h ({C.HORLOGE_H//24} j), "
          f"fenetre {C.FENETRE_H} h, k={C.K_PAR_JAMBE} par jambe")
    print(f"  cout par jambe et par aller-retour : {cout*10_000:.1f} bps "
          f"({TAKER_BPS} taker x2 + {SLIPPAGE_BPS} slippage x2)")
    print()
    if principal.get("verdict") != C.MESURE:
        print(f"  NON MESURABLE : {principal.get('motif')}")
        print(f"  {principal.get('lecture', '')}")
        return 1
    print("  RESULTAT A LA CONVENTION — funding ET prix")
    print(f"  {principal['lecture']}")
    if principal.get("prix_pnl_moyen") is not None:
        print(f"  decomposition : funding {principal['funding_moyen']*100:+.3f} % "
              f"+ prix {principal['prix_pnl_moyen']*100:+.3f} % "
              f"- cout {cout*100:.3f} % = net {principal['net_moyen']*100:+.3f} %")
        if sans_prix.get("verdict") == C.MESURE:
            print(f"  (le funding SEUL aurait annonce "
                  f"{sans_prix['annualise']*100:+.2f} %/an -> le prix "
                  f"{'CONFIRME' if principal['annualise'] >= sans_prix['annualise'] else 'CORRIGE'} "
                  f"vers {principal['annualise']*100:+.2f} %/an)")
    print(f"  dispersion des revisions : min {principal['net_min']*100:+.3f} % | "
          f"median {principal['net_median']*100:+.3f} % | max {principal['net_max']*100:+.3f} %")
    print()
    print("  DISPERSION SUR k (publiee expres, AUCUN k elu)")
    for k in sorted(balayage["annualises"]):
        marque = "  <- convention" if k == balayage["convention"] else ""
        print(f"    k={k:<3} annualise {balayage['annualises'][k]*100:+7.2f} %{marque}")
    part = balayage.get("part_des_k_positifs")
    if part is not None:
        print(f"    {part:.0%} des k donnent un annualise positif")
    print(f"    {balayage['avertissement']}")
    print()

    # Les portes de survie : ce rendement s'applique au notionnel SURVIVABLE, pas au capital.
    annualise = principal.get("annualise")
    if annualise is not None:
        print("  APRES LES PORTES DE SURVIE (sur ton capital reel)")
        for nom, levmax, exc in (("BTC", 40, 1.16), ("SOL", 20, 4.00)):
            mmr = S.taux_de_maintenance(levmax)
            plafond = S.levier_maximum_survivable(excursion=exc, taux_maintenance=mmr)
            noti = plafond * float(args.capital)
            placable = S.ordre_placable(notionnel_usd=noti / (2 * C.K_PAR_JAMBE))
            print(f"    {nom:<4} levier max {plafond:.2f}x -> notionnel {noti:.0f} USD "
                  f"| par jambe {noti/(2*C.K_PAR_JAMBE):.1f} USD -> {placable['verdict']}")
            print(f"         rendement sur capital : {annualise*plafond*100:+.2f} %/an "
                  f"= {annualise*plafond*float(args.capital):+.2f} USD/an")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
