#!/usr/bin/env python3
"""EXECUTEUR PAPER EN AVANT du livre transversal inverse — il tient un livre de comptes reel.

POURQUOI UN EXECUTEUR A PART, ET PAS UNE GREFFE DANS LE MOTEUR
---------------------------------------------------------------
`LANCER_HYPERSMART` n'est pas une boucle : c'est un menu qui demarre un serveur UI
(`python -m hl_observer ui`) plus un poller, au-dessus des collecteurs dont la **campagne en cours
depend**. Greffer une strategie dans ce chemin de decision sans l'avoir compris entierement
risquerait la collecte — et une collecte perdue ne se rattrape pas. Cet executeur fait donc le
meme travail a cote : il lit le coffre, decide, et ecrit son propre grand livre.

Il respecte le contrat de `strategies/` : la strategie est **pure et propose**, cet outil
**execute en simulation**. Rien ici ne touche au reseau ni a une cle.

CE QU'IL MESURE, ET QUI N'EST PAS UN REJEU
------------------------------------------
Le protocole gele (`docs/PREENREGISTREMENT_5USD_V2.md`) juge en REJOUANT l'histoire posterieure au
gel. Cet executeur, lui, decide **au fil du temps** : a chaque passage il ne voit que le passe, et
sa decision est ECRITE avant que le resultat n'existe. C'est la difference entre « la strategie
aurait gagne » et « la strategie a gagne ». Les deux mesures doivent converger ; si elles
divergent, la divergence dit ou l'execution mange le gain.

CE QU'IL REFUSE
---------------
* **rejouer une decision deja prise** : un instant deja present au grand livre est ignore. Sans
  cela, relancer l'outil deux fois doublerait les positions et fabriquerait un PnL ;
* **marquer une position sans prix** : pas de prix -> la position reste ouverte et NON marquee,
  jamais marquee a son prix d'entree (ce qui afficherait un PnL de zero au lieu d'un inconnu) ;
* **ouvrir un livre non placable** : la strategie refuse d'elle-meme sous le notionnel minimum, et
  son refus est ENREGISTRE au journal — un refus est une observation, pas un silence.

PAPER / lecture seule. Aucun ordre, aucune cle, aucune requete reseau.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import statistics
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

GRAND_LIVRE = Path("runtime") / "data" / "paper_carry_inverse.json"
SCHEMA = "hypersmart.paper_carry_inverse.v1"

#: Conventions du protocole gele. Non reglables : un executeur qui laisserait regler l'horizon
#: apres avoir vu le resultat transformerait la mesure en recherche.
HORIZON_H = 96
FENETRE_H = 96
K = 3
TAKER_BPS = 4.5
SLIPPAGE_DEFAUT_BPS = 4.17


def charger_livre(chemin: Path) -> dict:
    try:
        d = json.loads(chemin.read_text(encoding="utf-8"))
        if d.get("_schema") == SCHEMA:
            return d
    except (OSError, ValueError, AttributeError):
        pass
    return {"_schema": SCHEMA, "positions": [], "fermees": [], "refus": [],
            "capital_initial_usd": None}


def sauver_livre(chemin: Path, livre: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(livre, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(chemin)


def main(argv: list[str] | None = None) -> int:
    # Preserve historical research code without permitting a second economic
    # runtime/ledger while Copy-Vault is the sole active strategy family.
    from hl_observer.strategies.active_scope import strategy_can_materialize

    if not strategy_can_materialize("carry"):
        print("DISABLED_BY_SCOPE:carry")
        return 2
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--capital", type=float, default=350.0)
    p.add_argument("--levier", type=float, default=4.26,
                   help="levier du dimensionnement en marge croisee")
    p.add_argument("--une-fois", action="store_true", default=True)
    args = p.parse_args(argv)
    root = Path(args.root)

    from hl_observer.strategies.carry_transversal_inverse import (
        CarryTransversalInverse, Refus)
    from mesurer_strategie import charger_funding, charger_prix, slippage_bps, FUNDING, BOUGIES

    funding = charger_funding(root / FUNDING)
    prix = charger_prix(root / BOUGIES)
    if not funding or not prix:
        print("[paper] coffre vide : rien a decider.")
        return 2
    slip, source_slip = slippage_bps(root)
    cout_jambe = 2 * (TAKER_BPS + slip) / 1e4

    heures = sorted({h for s in funding.values() for h in s})
    maintenant = heures[-1]
    chemin = root / GRAND_LIVRE
    livre = charger_livre(chemin)
    if livre["capital_initial_usd"] is None:
        livre["capital_initial_usd"] = float(args.capital)
    notionnel = float(args.capital) * float(args.levier)

    # ---- 1) MARQUER et FERMER les positions arrivees a echeance
    encore: list[dict] = []
    for pos in livre["positions"]:
        echeance = int(pos["instant_h"]) + HORIZON_H
        serie = prix.get(pos["coin"], {})
        if maintenant < echeance:
            encore.append(pos)
            continue
        entree, sortie = serie.get(int(pos["instant_h"])), serie.get(echeance - 1)
        if entree is None or sortie is None or entree <= 0:
            # Pas de prix : la position reste OUVERTE et non marquee. La marquer a son prix
            # d'entree afficherait un PnL de zero la ou le resultat est INCONNU.
            pos["prix_manquant"] = True
            encore.append(pos)
            continue
        variation = (sortie - entree) / entree
        sens = 1 if pos["sens"] == "LONG" else -1
        # funding ENCAISSE sur la periode detenue (un long PAIE un funding positif)
        f = funding.get(pos["coin"], {})
        porte = sum(-sens * float(f[h]) for h in range(int(pos["instant_h"]), echeance)
                    if h in f)
        rendement = sens * variation + porte - cout_jambe
        livre["fermees"].append({**{k: pos[k] for k in ("coin", "sens", "instant_h", "notionnel")},
                                 "ferme_h": echeance, "prix_pnl": sens * variation,
                                 "funding": porte, "cout": cout_jambe,
                                 "rendement": rendement,
                                 "pnl_usd": rendement * float(pos["notionnel"])})
    livre["positions"] = encore

    # ---- 2) DECIDER, une seule fois par instant
    deja = {int(x["instant_h"]) for x in livre["positions"]} | \
           {int(x["instant_h"]) for x in livre["fermees"]} | \
           {int(x["instant_h"]) for x in livre["refus"]}
    strategie = CarryTransversalInverse.default()
    if maintenant in deja:
        print(f"[paper] instant {maintenant} deja decide : aucune nouvelle position "
              "(rejouer doublerait le livre).")
    else:
        out = strategie.proposer(funding, instant_h=maintenant, notionnel_total_usd=notionnel,
                                 fenetre_h=FENETRE_H, k=K)
        if isinstance(out, Refus):
            # Un refus est une OBSERVATION : on l'enregistre, on ne le passe pas sous silence.
            livre["refus"].append({"instant_h": maintenant, "motif": out.motif,
                                   "detail": out.detail})
            print(f"[paper] REFUS a l'instant {maintenant} : {out.motif} — {out.detail}")
        else:
            for intention in out:
                livre["positions"].append({
                    "coin": intention.coin, "sens": intention.side.value,
                    "instant_h": maintenant,
                    "notionnel": float(intention.target_notional_usdt)})
            print(f"[paper] {len(out)} positions ouvertes a l'instant {maintenant} "
                  f"({out[0].target_notional_usdt:.2f} USD/jambe)")

    sauver_livre(chemin, livre)

    # ---- 3) RENDRE COMPTE
    fermees = livre["fermees"]
    print()
    print("GRAND LIVRE PAPER — livre transversal inverse")
    print("=" * 72)
    print(f"  capital {livre['capital_initial_usd']:.0f} USD x levier {args.levier:.2f} "
          f"= {notionnel:.0f} USD de notionnel")
    print(f"  cout {cout_jambe*1e4:.1f} bps/jambe (slippage {slip:.2f} b, {source_slip})")
    print(f"  positions ouvertes : {len(livre['positions'])} | fermees : {len(fermees)} | "
          f"refus : {len(livre['refus'])}")
    if not fermees:
        print()
        print("  Aucune position fermee : il faut 96 h de detention pour un premier resultat.")
        print("  C'est voulu — un PnL avant l'echeance serait une marque, pas un gain.")
        return 0
    pnl = sum(float(x["pnl_usd"]) for x in fermees)
    rends = [float(x["rendement"]) for x in fermees]
    jours = (max(int(x["ferme_h"]) for x in fermees)
             - min(int(x["instant_h"]) for x in fermees)) / 24.0
    print()
    print(f"  PnL cumule : **{pnl:+.2f} USD** sur {jours:.1f} jour(s) couverts")
    if jours > 0:
        print(f"  soit {pnl/jours:+.3f} USD/jour")
    print(f"  par jambe : moyenne {statistics.fmean(rends)*100:+.3f} % | "
          f"mediane {statistics.median(rends)*100:+.3f} % | "
          f"{sum(1 for r in rends if r > 0)}/{len(rends)} positives")
    manquants = sum(1 for x in livre["positions"] if x.get("prix_manquant"))
    if manquants:
        print(f"  /!\\ {manquants} position(s) echue mais SANS PRIX : laissees ouvertes et non "
              "marquees, jamais marquees a zero.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
