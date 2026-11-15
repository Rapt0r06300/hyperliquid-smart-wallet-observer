#!/usr/bin/env python3
"""L'OUTIL OFFICIEL : une seule commande, un seul chiffre, toute la chaine.

POURQUOI IL REMPLACE LES AUTRES
-------------------------------
Les mesures de la session du 14/11 vivaient dans des scripts jetables, et l'outil du depot
(`mesurer_carry_patient.py`) tournait encore avec les anciennes conventions (`k=5`, detention
720 h, slippage SUPPOSE a 2 bps). Resultat : **le depot contredisait le protocole gele**, et
quiconque lancait l'outil obtenait un autre chiffre. Cet outil assemble la chaine complete, dans
l'ordre ou chaque maillon a ete etabli :

1. **signal** : funding brut, livre INVERSE (long le funding haut). Le carry est refute a -41,3 %/an
   une fois le prix compte ; le momentum direct a -44,2 % ; la variation du funding aussi.
2. **detention 96 h** : retenue sur le plus faible ecart train/test du balayage d'horizon
   (1,4 point contre 53,5 a 24 h), pas sur le rendement le plus eleve.
3. **k=3** : retenu sur sa STABILITE (positif sur les trois tiers, ecart-type 17,9 contre 94,4 pour
   k=1), pas sur son sommet.
4. **couverture 100 %** : la jambe longue perd -9,2 %/an seule, mais sans elle le repli passe de
   12,1 % a 42,7 %. Elle se paie en RISQUE, et le balayage est monotone.
5. **8 tranches** : le decoupage ne change pas le rendement moyen, seulement le moment d'entree.
6. **cout MESURE** : 4,5 bps de frais taker + **4,36 bps de slippage mesure sur 60 000 carnets**
   (et non 2 bps supposes). Le scenario maker est affiche a part car le remplissage passif a
   l'echelle de l'heure n'est PAS mesure.
7. **dimensionnement en marge croisee** : `N < C/(D x facteur + mmr)`, avec D = pire repli du
   portefeuille TRANCHE sur TOUTES les fenetres.

CE QU'IL REFUSE DE FAIRE
------------------------
* **aucun parametre de strategie n'est reglable** : un outil qui laisserait regler `k` apres avoir
  vu le resultat transformerait la mesure en recherche. Seules la fenetre et le capital le sont.
* **il DECLARE la taille de l'univers** sur lequel il tourne. Le protocole a ete gele sur 90 coins ;
  si l'univers s'est elargi, le resultat n'est plus comparable et l'outil le dit.
* **il affiche train/test ET les trois tiers**, jamais la seule moyenne : c'est la dispersion entre
  periodes qui dit si un chiffre tient.

PAPER / lecture seule.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))

SHARDS = Path("runtime") / "coffre_certifie" / "local" / "shards"
FUNDING = SHARDS / "funding_history"
BOUGIES = SHARDS / "candle"
SLIPPAGE_MESURE = Path("runtime") / "data" / "slippage_mesure.json"

# --- configuration GELEE (docs/PREENREGISTREMENT_5USD.md). Non reglable en ligne de commande.
K = 3
#: 14/11/2026 — DIVERSIFICATION PAR HORIZON. Le decoupage en tranches diversifie le MOMENT d'entree
#: a horizon fixe ; ces cinq horizons diversifient l'horizon LUI-MEME. Le balayage les avait tous
#: trouves positifs, donc ce sont cinq livres imparfaitement correles. Mesure : le repli du
#: portefeuille tombe de **6,35 % a 2,79 %** quand le brut reste identique (+68,8 % -> +70,5 %), ce
#: qui DOUBLE le levier autorise. Gain stable sur TOUTES les periodes : x1,52 a x2,27, jamais moins.
#: **Aucune selection** : les cinq sont equiponderes, et le meilleur sous-ensemble trie a la main ne
#: fait que 3 % de mieux — il n'y a donc rien a cueillir.
HORIZONS = (24, 48, 96, 168, 336)
DETENTION_H = 96          # l'horizon de reference, conserve pour la comparaison
FENETRE_H = 96
TRANCHES = 8
PAS_H = 12
#: 14/11/2026 — MMR MESURE, PLUS SUPPOSE. Je supposais 5 % (palier alt 10x) et je PREDISAIS une
#: valeur plus BASSE encore (2,5 %) : la mesure donne **12,32 %**, ponderee par la frequence de
#: selection reelle sur 11 514 jambes. Cause, et elle etait sous mes yeux : j'avais deja mesure que
#: **l'edge vit dans les coins volatils** (la ponderation 1/volatilite le detruisait), et la venue
#: assigne a ces coins le levier maximum le PLUS BAS — donc le mmr le plus HAUT. XMR a 5x, VVV,
#: GRASS, MOVE, CHIP, 2Z a 3x. Les deux faits sont le meme fait.
#: La maintenance vaut `somme(notionnel_i x mmr_i)`, soit `notionnel x moyenne(mmr_i)` pour un livre
#: equipondere : c'est donc la MOYENNE PONDEREE qu'il faut, pas le pire coin (16,67 %), qui
#: sur-dimensionnerait la marge d'un tiers.
MMR = 0.1232
TAKER_BPS = 4.5
MAKER_BPS = 1.5
CAPTURE_BPS = 0.69        # mesure, capture passive moyenne
ADVERSE_BPS = 2.16        # mesure, derive adverse a 10 s
SLIPPAGE_DEFAUT_BPS = 4.36
UNIVERS_DU_GEL = 90


def charger_funding(dossier: Path) -> dict[str, dict[int, float]]:
    par_coin: dict[str, dict[int, float]] = defaultdict(dict)
    for fichier in sorted(dossier.glob("*.jsonl.gz")) if dossier.is_dir() else ():
        try:
            with gzip.open(fichier, "rt", encoding="utf-8", errors="replace") as flux:
                for ligne in flux:
                    if not ligne.strip().startswith("{"):
                        continue
                    try:
                        o = json.loads(ligne)
                    except ValueError:
                        continue
                    coin, instant, taux = o.get("coin"), o.get("ts_ms"), o.get("funding")
                    if coin and instant is not None and taux is not None:
                        with contextlib.suppress(TypeError, ValueError):
                            par_coin[str(coin)][int(instant) // 3_600_000] = float(taux)
        except OSError:
            continue
    return par_coin


def charger_prix(dossier: Path) -> dict[str, dict[int, float]]:
    """Clotures HORAIRES uniquement : melanger des pas differents ferait coexister deux
    definitions de « la cloture de cette heure »."""
    par_coin: dict[str, dict[int, float]] = defaultdict(dict)
    for fichier in sorted(dossier.glob("*.jsonl.gz")) if dossier.is_dir() else ():
        try:
            with gzip.open(fichier, "rt", encoding="utf-8", errors="replace") as flux:
                for ligne in flux:
                    if not ligne.strip().startswith("{"):
                        continue
                    try:
                        o = json.loads(ligne)
                    except ValueError:
                        continue
                    if o.get("interval") != "1h":
                        continue
                    coin, instant, cloture = o.get("coin"), o.get("open_ts_ms"), o.get("close")
                    if coin and instant is not None and cloture is not None:
                        with contextlib.suppress(TypeError, ValueError):
                            par_coin[str(coin)][int(instant) // 3_600_000] = float(cloture)
        except OSError:
            continue
    return par_coin


def heures_exploitables(funding, prix) -> list[int]:
    """Les heures ou l'on a **A LA FOIS** du funding et un prix. **La seule fenetre mesurable.**

    **LE DEFAUT QUE CECI CORRIGE, ET IL ETAIT GRAVE.** Les periodes TRAIN / TEST / tiers etaient
    decoupees sur l'historique du **FUNDING SEUL**. Or les deux sources n'ont pas la meme
    profondeur : le funding remonte a ~1 100 jours, les bougies horaires a 208. Resultat observe le
    15/11 : pendant que le rattrapage allongeait le funding de 211 a 275 jours, **les bornes des
    periodes se sont deplacees** et le chiffre de reference est passe de **+3,02 a +1,27 USD/jour**
    — sans qu'aucune ligne de code de la strategie ait change, et sans le moindre avertissement.

    **Un labo dont les resultats bougent quand les donnees grandissent ne mesure rien.** Les
    periodes se calculent donc sur l'INTERSECTION, qui ne depend plus de la source la plus profonde.

    On prend l'union par coin de chaque cote, puis l'intersection : un instant est exploitable des
    qu'un coin au moins porte les deux. Exiger que TOUS les coins les portent exclurait toute heure
    ou un seul coin manque, ce qui est la regle inverse de celle du classement — lui n'a besoin que
    des coins classables.
    """
    h_f = {h for serie in funding.values() for h in serie}
    h_p = {h for serie in prix.values() for h in serie}
    return sorted(h_f & h_p)


def slippage_bps(root: Path) -> tuple[float, str]:
    """Slippage retenu. Lu depuis la mesure persistee si elle existe, sinon la valeur mesuree le
    14/11 — jamais une valeur inventee, et la SOURCE est toujours dite."""
    chemin = root / SLIPPAGE_MESURE
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        valeur = float(donnees["slippage_moyen_bps"])
        if valeur > 0:
            return valeur, f"mesure persistee ({chemin.name}, n={donnees.get('n', '?')})"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return SLIPPAGE_DEFAUT_BPS, "mesure du 14/11 sur 60 000 carnets (non persistee)"


def series_par_horizon(funding, prix, *, cout: float) -> dict[int, dict[int, float]]:
    """Un net par horizon et par instant de DECISION, sur un pas commun de 12 h.

    Le depart commun est `max(HORIZONS)` apres le debut : sans cela les horizons courts
    disposeraient de fenetres que les longs n'ont pas, et la comparaison serait faussee.
    """
    from hl_observer.backtesting import carry_patient as C
    # La fenetre vient de l'INTERSECTION funding ∩ prix, jamais du funding seul : sinon chaque jour
    # de rattrapage deplace les bornes et change les chiffres en silence.
    heures = heures_exploitables(funding, prix)
    # 15/11 — L'INDEX EST CONSTRUIT UNE SEULE FOIS, pour les cinq horizons et tous les instants.
    # Sans lui, la moyenne des 96 h etait recalculee a partir de zero pour chaque coin et chaque
    # instant : 31 ms par revision, 11 min par lancement, et **1,6 h projetee** a 1 100 jours et
    # 261 coins — alors que le reaper memoire de ce PC coupe les runs au-dela de ~30 min.
    index = {coin: C.index_glissant(serie) for coin, serie in funding.items()}
    sortie: dict[int, dict[int, float]] = {}
    for horizon in HORIZONS:
        serie: dict[int, float] = {}
        instant = heures[0] + max(HORIZONS)
        while instant <= heures[-1] - horizon:
            r = C.une_revision(funding, instant=instant, duree_h=horizon,
                               fenetre_h=min(168, max(24, horizon)), k=K, prix=prix,
                               inverser=True, index=index)
            if r.get("verdict") == C.MESURE and r.get("prix_pnl") is not None:
                serie[instant] = r["total_brut"] - cout
            instant += PAS_H
        sortie[horizon] = serie
    return sortie


def juger_multi(series: dict[int, dict[int, float]], *, capital: float, facteur: float,
                debut=None, fin=None, repli_impose: float | None = None) -> dict | None:
    """Le portefeuille multi-horizons : brut pondere, et repli de la SERIE du portefeuille.

    PIEGE ECARTE : on ne somme pas les replis des horizons (ce serait supposer qu'ils perdent
    toujours ensemble) et on ne les divise pas par leur nombre (ce serait supposer qu'ils ne
    perdent jamais ensemble). A tout instant, la valeur du livre est la moyenne ponderee des
    detentions ACTIVES de chaque horizon : c'est cette serie-la que la marge regarde.
    """
    from hl_observer.backtesting import dimensionnement_croise as D
    instants = sorted(set.intersection(*(set(s) for s in series.values()))) if series else []
    if len(instants) < TRANCHES:
        return None
    poids = 1.0 / len(series)
    bruts = []
    for horizon, serie in series.items():
        vals = [v for t, v in serie.items()
                if (debut is None or t >= debut) and (fin is None or t < fin)]
        if len(vals) < TRANCHES:
            return None
        bruts.append(poids * statistics.fmean(vals) / horizon * 8760.0)
    brut = sum(bruts)
    if repli_impose is None:
        pertes = []
        for i, t in enumerate(instants):
            total = 0.0
            for horizon, serie in series.items():
                actives = max(1, horizon // PAS_H)
                fenetre = [serie[u] for u in instants[max(0, i - actives + 1):i + 1]
                           if u in serie]
                if fenetre:
                    total += poids * statistics.fmean(fenetre)
            pertes.append(total)
        repli_impose = abs(min(pertes)) if pertes else None
    if not repli_impose or repli_impose <= 0:
        return None
    bloc = D.notionnel_maximum(capital_usd=capital, repli=repli_impose, taux_maintenance=MMR,
                               facteur_de_securite=facteur)
    if bloc.get("verdict") != D.MESURE:
        return None
    levier = bloc["levier"]
    toutes = [v for s in series.values() for v in s.values()]
    return {"n": len(instants), "brut": brut, "repli": repli_impose, "levier": levier,
            "sur_capital": brut * levier, "usd_jour": brut * levier * capital / 365.0,
            "positives": sum(1 for x in toutes if x > 0) / len(toutes),
            "liquide_si": facteur * repli_impose + MMR}


def nets(funding, prix, *, debut=None, fin=None, cout: float) -> list[float]:
    from hl_observer.backtesting import carry_patient as C
    heures = heures_exploitables(funding, prix)
    if not heures:
        return []
    index = {coin: C.index_glissant(serie) for coin, serie in funding.items()}
    sortie: list[float] = []
    instant = heures[0] + FENETRE_H
    while instant <= heures[-1] - DETENTION_H:
        if (debut is None or instant >= debut) and (fin is None or instant < fin):
            r = C.une_revision(funding, instant=instant, duree_h=DETENTION_H,
                               fenetre_h=FENETRE_H, k=K, prix=prix, inverser=True,
                               index=index)
            if r.get("verdict") == C.MESURE and r.get("prix_pnl") is not None:
                sortie.append(r["total_brut"] - cout)
        instant += PAS_H
    return sortie


def juger(nets_: list[float], *, capital: float, facteur: float,
          repli_impose: float | None = None) -> dict | None:
    """`repli_impose` vient de l'HISTOIRE LA PLUS LONGUE, jamais de la periode mesuree.

    Sans cela, une periode courte et chanceuse — qui n'a simplement pas rencontre la pire fenetre —
    obtiendrait PLUS de levier qu'une periode longue. C'est la troisieme fois dans cette session que
    ce piege se presente sous une forme differente : le repli de dimensionnement doit toujours venir
    du plus grand echantillon disponible, car un livre ne CHOISIT pas la fenetre dans laquelle il
    tombe.
    """
    from hl_observer.backtesting import dimensionnement_croise as D
    if len(nets_) < TRANCHES:
        return None
    brut = statistics.fmean(nets_) / DETENTION_H * 8760.0
    repli = repli_impose if repli_impose is not None else D.repli_tranche(nets_,
                                                                         tranches=TRANCHES)
    if repli is None or repli <= 0:
        return None
    bloc = D.notionnel_maximum(capital_usd=capital, repli=repli, taux_maintenance=MMR,
                               facteur_de_securite=facteur)
    if bloc.get("verdict") != D.MESURE:
        return None
    levier = bloc["levier"]
    return {"n": len(nets_), "brut": brut, "repli": repli, "levier": levier,
            "sur_capital": brut * levier, "usd_jour": brut * levier * capital / 365.0,
            "positives": sum(1 for x in nets_ if x > 0) / len(nets_),
            "liquide_si": facteur * repli + MMR}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--capital", type=float, default=350.0)
    p.add_argument("--facteur", type=float, default=4.0,
                   help="facteur de securite du dimensionnement (choix de RISQUE)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.root)

    funding = charger_funding(root / FUNDING)
    prix = charger_prix(root / BOUGIES)
    if not funding or not prix:
        print("[strategie] donnees absentes dans le coffre.")
        return 2
    heures = heures_exploitables(funding, prix)
    h_funding = sorted({h for s in funding.values() for h in s})
    h_prix = sorted({h for s in prix.values() for h in s})
    if not heures:
        print("[strategie] aucune heure avec FUNDING ET PRIX : rien de mesurable.")
        return 2
    slip, source_slip = slippage_bps(root)
    cout_taker = 2 * (TAKER_BPS + slip) / 1e4
    cout_maker = 2 * (MAKER_BPS - CAPTURE_BPS + ADVERSE_BPS) / 1e4

    bornes = [heures[0], heures[len(heures)//3], heures[2*len(heures)//3], heures[-1] + 1]
    milieu = heures[len(heures)//2]
    periodes = [("TOUT ", None, None), ("TRAIN", None, milieu), ("TEST ", milieu, None),
                ("tiers1", bornes[0], bornes[1]), ("tiers2", bornes[1], bornes[2]),
                ("tiers3", bornes[2], bornes[3])]

    from hl_observer.backtesting import dimensionnement_croise as D
    resultats: dict[str, dict] = {}
    replis: dict[str, float] = {}
    for nom_cout, cout in (("taker", cout_taker), ("maker", cout_maker)):
        # Le repli de DIMENSIONNEMENT est calcule UNE FOIS sur toute l'histoire, puis impose a
        # toutes les periodes : une periode courte ne doit pas gagner du levier par chance.
        complet = nets(funding, prix, cout=cout)
        repli = D.repli_tranche(complet, tranches=TRANCHES)
        if repli is None or repli <= 0:
            continue
        replis[nom_cout] = repli
        for nom, d, f in periodes:
            r = juger(nets(funding, prix, debut=d, fin=f, cout=cout),
                      capital=args.capital, facteur=args.facteur, repli_impose=repli)
            if r:
                resultats[f"{nom_cout}/{nom.strip()}"] = r

    # Le multi-horizons est calcule AVANT toute sortie : sans cela, `--json` se terminait avant le
    # bloc multi et le JSON ne disait PAS la meme chose que le texte. Deux sorties du meme outil qui
    # divergent, c'est la porte ouverte a citer un chiffre que l'outil n'a jamais affiche.
    from hl_observer.backtesting import dimensionnement_croise as D0
    series_par_cout: dict[str, dict] = {}
    replis: dict[str, float] = {}
    for nom_cout, cout in (("taker", cout_taker), ("maker", cout_maker)):
        series = series_par_horizon(funding, prix, cout=cout)
        complet = juger_multi(series, capital=args.capital, facteur=args.facteur)
        if not complet:
            continue
        series_par_cout[nom_cout] = series
        replis[nom_cout] = complet["repli"]
        for nom, d, f in periodes:
            r = juger_multi(series, capital=args.capital, facteur=args.facteur, debut=d, fin=f,
                            repli_impose=complet["repli"])
            if r:
                resultats[f"multi-{nom_cout}/{nom.strip()}"] = r

    if args.json:
        print(json.dumps({"univers": len(funding), "slippage_bps": slip, "mmr": MMR,
                          "facteur": args.facteur, "capital": args.capital,
                          "resultats": resultats}, ensure_ascii=False, indent=1, default=str))
        return 0

    print("STRATEGIE — MESURE OFFICIELLE")
    print("=" * 84)
    print(f"  configuration GELEE : k={K}, detention {DETENTION_H} h, {TRANCHES} tranches "
          f"(/{PAS_H} h), couverture 100 %, mmr {MMR:.0%}, facteur {args.facteur:.0f}")
    print(f"  capital {args.capital:.0f} USD | slippage {slip:.2f} bps ({source_slip})")
    print(f"  cout : taker {cout_taker*1e4:.1f} bps/jambe | maker {cout_maker*1e4:.1f} bps/jambe")
    print(f"  univers : **{len(funding)} coins** de funding, {len(prix)} de prix")
    print(f"  collecte : funding {len(h_funding)} h ({len(h_funding)/24:.0f} j) | "
          f"prix {len(h_prix)} h ({len(h_prix)/24:.0f} j)")
    print(f"  **MESURABLE : {len(heures)} h ({len(heures)/24:.0f} j)** = l'intersection des deux")
    perdu = len(h_funding) - len(heures)
    if perdu > 24:
        print(f"  ({perdu} h de funding ({perdu/24:.0f} j) sans prix en face : collectees mais "
              "non mesurables. Le pas JOURNALIER est celui qui leur donnera un prix — il remonte")
        print("   a 1 101 jours contre 208 en horaire.)")
    if len(funding) != UNIVERS_DU_GEL:
        print(f"  /!\\ LE PROTOCOLE A ETE GELE SUR {UNIVERS_DU_GEL} COINS. L'univers en compte "
              f"{len(funding)} :")
        print("      le resultat ci-dessous n'est PLUS comparable au preenregistrement, et doit")
        print("      etre traite comme un NOUVEAU protocole a juger sur une fenetre jamais vue.")
    print()
    for nom_cout in ("taker", "maker"):
        libelle = ("taker MESURE (retenu)" if nom_cout == "taker"
                   else "maker (remplissage horaire NON mesure)")
        print(f"  --- {libelle} ---")
        print(f"  repli de dimensionnement (toute l'histoire) : "
              f"{replis.get(nom_cout, float('nan'))*100:.2f} % — impose a TOUTES les periodes")
        print(f"  {'periode':<9}{'n':>5}{'brut/an':>10}{'repli':>8}{'levier':>8}"
              f"{'/capital':>10}{'USD/jour':>10}{'pos.':>7}")
        for nom, _, _ in periodes:
            r = resultats.get(f"{nom_cout}/{nom.strip()}")
            if not r:
                print(f"  {nom:<9}{'NON JUGEABLE (< ' + str(TRANCHES) + ' fenetres)':>48}")
                continue
            print(f"  {nom:<9}{r['n']:>5}{r['brut']*100:>+9.1f}%{r['repli']*100:>7.2f}%"
                  f"{r['levier']:>7.2f}x{r['sur_capital']*100:>+9.1f}%"
                  f"{r['usd_jour']:>+9.2f}U{r['positives']:>6.0%}")
        print()
    # --- le portefeuille MULTI-HORIZONS, qui est la configuration retenue
    print("  === PORTEFEUILLE MULTI-HORIZONS "
          + " + ".join(f"{h} h" for h in HORIZONS) + " ===")
    for nom_cout in ("taker", "maker"):
        libelle = ("taker MESURE (retenu)" if nom_cout == "taker"
                   else "maker (remplissage horaire NON mesure)")
        if nom_cout not in replis:
            print(f"  --- {libelle} --- NON JUGEABLE")
            continue
        print(f"  --- {libelle} --- repli du portefeuille {replis[nom_cout]*100:.2f} % "
              f"(impose a toutes les periodes)")
        print(f"  {'periode':<9}{'brut/an':>10}{'levier':>8}{'/capital':>10}{'USD/jour':>10}")
        for nom, _d, _f in periodes:
            r = resultats.get(f"multi-{nom_cout}/{nom.strip()}")
            if not r:
                print(f"  {nom:<9}{'NON JUGEABLE':>38}")
                continue
            print(f"  {nom:<9}{r['brut']*100:>+9.1f}%{r['levier']:>7.2f}x"
                  f"{r['sur_capital']*100:>+9.1f}%{r['usd_jour']:>+9.2f}U")
        print()
    pires = [r for c, r in resultats.items() if c.startswith("multi-taker/tiers")]
    if pires:
        borne = min(pires, key=lambda r: r["usd_jour"])
        print(f"  BORNE BASSE HONNETE (multi-horizons, taker, pire tiers) : "
              f"**{borne['usd_jour']:+.2f} USD/jour**")
    # Le chiffre de REFERENCE est celui du portefeuille multi-horizons : c'est la configuration
    # retenue. Annoncer l'ancien mono-horizon serait annoncer un resultat qu'on n'exploite plus.
    ref = resultats.get("multi-taker/TEST")
    mono = resultats.get("taker/TEST")
    if ref:
        print(f"  CHIFFRE DE REFERENCE — multi-horizons, taker mesure, hors echantillon, facteur "
              f"{args.facteur:.0f} : **{ref['usd_jour']:+.2f} USD/jour**")
        print(f"  liquidation si le livre perd {ref['liquide_si']:.1%}")
        if mono:
            print(f"  (le mono-horizon 96 h donnait {mono['usd_jour']:+.2f} USD/jour : "
                  f"x{ref['usd_jour']/mono['usd_jour']:.2f})")
    plafond = resultats.get("multi-maker/TEST")
    if plafond:
        print(f"  PLAFOND si l'execution passive tient : {plafond['usd_jour']:+.2f} USD/jour "
              "— le remplissage passif a l'echelle de l'HEURE n'est PAS mesure, donc ce chiffre")
        print("  est un plafond, pas une estimation.")
    print()
    print("  Lire la DISPERSION entre periodes, jamais la seule moyenne : c'est elle qui dit si")
    print("  le chiffre tient. Et le repli de dimensionnement vient de TOUTE l'histoire, jamais")
    print("  de la periode mesuree — sinon une periode courte gagne du levier par chance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
