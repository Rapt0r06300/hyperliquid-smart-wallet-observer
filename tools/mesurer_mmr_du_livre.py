#!/usr/bin/env python3
"""MESURE le `mmr` REEL du livre, au lieu de le supposer au palier le plus dur.

POURQUOI MAINTENANT. L'identite du resultat est `USD/jour = capital x brut / (D x facteur + mmr)`.
Avec le multi-horizons, D est tombe a **2,79 %**, et le denominateur vaut `4 x 0,0279 + 0,05` :
**le mmr est passe de 16 % a 31 % du total**. En faisant baisser le repli, la diversification a
PROMU la marge de maintenance au rang de deuxieme contrainte — et je l'avais supposee a 5 % en
appliquant le palier des altcoins (10x) a TOUT le livre.

Or la maintenance est une **somme ponderee par jambe** : `somme(notionnel_i x mmr_i)`. Le mmr du
livre est donc la moyenne ponderee des mmr des coins REELLEMENT retenus, et c'est une MESURE.

LA DONNEE MANQUAIT. Ni `asset_ctx` ni `hl_univers_perps.json` ne portent le levier maximum. Il
vient de l'endpoint public `meta` (`universe[].maxLeverage`) : **une seule requete en lecture
seule**, negligeable pour le debit partage avec la campagne. Elle est persistee pour n'etre faite
qu'une fois.

CE QUE CET OUTIL REFUSE. Un coin dont le levier maximum est inconnu n'est **PAS** suppose
favorable : il recoit le palier le plus dur rencontre, et le compte des inconnus est AFFICHE.
Supposer 1,25 % (reserve a BTC) sur un coin inconnu autoriserait un levier mortel.

PAPER / lecture seule. Aucun ordre, aucune cle.
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

CACHE = Path("runtime") / "data" / "levier_max_par_coin.json"
#: Palier le plus dur publie par la venue (3x -> mmr 16,7 %). Retenu pour tout coin INCONNU.
LEVIER_INCONNU = 3.0


def charger_leviers(root: Path, *, rafraichir: bool = False) -> tuple[dict[str, float], str]:
    chemin = root / CACHE
    if not rafraichir:
        try:
            d = json.loads(chemin.read_text(encoding="utf-8"))
            if isinstance(d.get("leviers"), dict) and d["leviers"]:
                return ({str(k): float(v) for k, v in d["leviers"].items()},
                        f"cache ({chemin.name}, {len(d['leviers'])} coins)")
        except (OSError, ValueError, KeyError, TypeError):
            pass
    from hl_observer.collection.univers_perps import poster_info
    meta = poster_info({"type": "meta"})
    leviers: dict[str, float] = {}
    for marche in (meta.get("universe") or ()) if isinstance(meta, dict) else ():
        if not isinstance(marche, dict) or marche.get("isDelisted") is True:
            continue
        nom, lev = marche.get("name"), marche.get("maxLeverage")
        if nom and lev:
            with contextlib.suppress(TypeError, ValueError):
                leviers[str(nom)] = float(lev)
    if leviers:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps({"_schema": "hypersmart.levier_max.v1",
                                      "leviers": leviers}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    return leviers, f"endpoint meta ({len(leviers)} coins, persiste)"


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--rafraichir", action="store_true")
    p.add_argument("--capital", type=float, default=350.0)
    p.add_argument("--facteur", type=float, default=4.0)
    args = p.parse_args(argv)
    root = Path(args.root)

    from hl_observer.backtesting import carry_patient as C
    from hl_observer.backtesting import dimensionnement_croise as D
    from hl_observer.backtesting import survie_position as S
    from mesurer_strategie import (charger_funding, charger_prix, slippage_bps, juger_multi,
                                   series_par_horizon, FUNDING, BOUGIES, HORIZONS, K, PAS_H,
                                   TAKER_BPS, MMR as MMR_SUPPOSE)

    leviers, source = charger_leviers(root, rafraichir=args.rafraichir)
    if not leviers:
        print("[mmr] aucun levier maximum obtenu.")
        return 2
    funding = charger_funding(root / FUNDING)
    prix = charger_prix(root / BOUGIES)
    slip, _ = slippage_bps(root)
    cout = 2 * (TAKER_BPS + slip) / 1e4

    # --- quels coins le livre retient-il REELLEMENT, et a quelle frequence ?
    heures = sorted({h for s in funding.values() for h in s})
    compte: dict[str, int] = {}
    total_jambes = 0
    for horizon in HORIZONS:
        instant = heures[0] + max(HORIZONS)
        while instant <= heures[-1] - horizon:
            r = C.une_revision(funding, instant=instant, duree_h=horizon,
                               fenetre_h=min(168, max(24, horizon)), k=K, prix=prix,
                               inverser=True)
            if r.get("verdict") == C.MESURE:
                for coin in list(r["shorts"]) + list(r["longs"]):
                    compte[coin] = compte.get(coin, 0) + 1
                    total_jambes += 1
            instant += PAS_H

    inconnus = sorted(c for c in compte if c not in leviers)
    # Le livre est equipondere en dollars, donc le poids d'un coin est sa FREQUENCE de selection.
    mmr_pondere = sum(
        (compte[c] / total_jambes) * S.taux_de_maintenance(leviers.get(c, LEVIER_INCONNU))
        for c in compte)
    pire = max(S.taux_de_maintenance(leviers.get(c, LEVIER_INCONNU)) for c in compte)

    print("MMR REEL DU LIVRE — mesure, plus suppose")
    print("=" * 76)
    print(f"  leviers maximum : {source}")
    print(f"  {len(compte)} coins distincts retenus sur {total_jambes} jambes ouvertes")
    if inconnus:
        print(f"  /!\\ {len(inconnus)} coin(s) de levier INCONNU -> palier le plus dur "
              f"({LEVIER_INCONNU:.0f}x, mmr {S.taux_de_maintenance(LEVIER_INCONNU):.1%}) : "
              f"{', '.join(inconnus[:8])}")
    print()
    print(f"  mmr SUPPOSE jusqu'ici (palier alt 10x)        : {MMR_SUPPOSE:.2%}")
    print(f"  mmr MESURE, pondere par frequence de selection : **{mmr_pondere:.2%}**")
    print(f"  mmr du PIRE coin retenu                        : {pire:.2%}")
    print()
    # --- les dix coins les plus retenus, avec leur palier
    print(f"  {'coin':<12}{'jambes':>8}{'part':>8}{'lev.max':>9}{'mmr':>8}")
    for coin, n in sorted(compte.items(), key=lambda kv: -kv[1])[:10]:
        lev = leviers.get(coin, LEVIER_INCONNU)
        print(f"  {coin:<12}{n:>8}{n/total_jambes:>7.1%}{lev:>8.0f}x"
              f"{S.taux_de_maintenance(lev):>7.2%}"
              + ("  (inconnu)" if coin not in leviers else ""))
    print()
    series = series_par_horizon(funding, prix, cout=cout)
    base = juger_multi(series, capital=args.capital, facteur=args.facteur)
    if not base:
        print("  portefeuille non jugeable.")
        return 1
    print(f"  EFFET SUR LE RESULTAT (facteur {args.facteur:.0f}, repli {base['repli']:.2%})")
    print(f"  {'hypothese de mmr':<34}{'mmr':>8}{'levier':>9}{'USD/jour':>11}")
    for nom, m in (("suppose (palier alt 10x)", MMR_SUPPOSE),
                   ("MESURE, pondere", mmr_pondere),
                   ("prudent : le PIRE coin retenu", pire)):
        bloc = D.notionnel_maximum(capital_usd=args.capital, repli=base["repli"],
                                   taux_maintenance=m, facteur_de_securite=args.facteur)
        if bloc.get("verdict") != D.MESURE:
            continue
        lev = bloc["levier"]
        print(f"  {nom:<34}{m:>7.2%}{lev:>8.2f}x"
              f"{base['brut'] * lev * args.capital / 365:>+10.2f}U")
    print()
    print("  LE MMR A RETENIR EST LA MOYENNE PONDEREE, pas le pire coin. La maintenance vaut")
    print("  `somme(notionnel_i x mmr_i)` : avec un livre equipondere, cela fait exactement")
    print("  `notionnel x moyenne(mmr_i)`. Le pire coin ne vaudrait que si TOUT le livre y etait,")
    print("  et le retenir sur-dimensionnerait la marge de plus d'un tiers.")
    print("  La ligne « pire coin » reste affichee comme borne superieure, pas comme choix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
