#!/usr/bin/env python3
"""FOUILLE DU COFFRE : parcourir les 162 millions de lignes par galeries, sans jamais tout charger.

POURQUOI. Le pont du labo plafonne a 8 000 000 de lignes materialisees, et le DIT. Sur un coffre de
162 286 723 lignes, cela veut dire qu'une etude portant sur tout le corpus voit au mieux 5 % de la
mine. Lever le plafond tuerait la machine ; la bonne reponse est de decouper.

`plan_de_fouille` calcule des GALERIES : des fenetres de temps contigues et disjointes dont chacune
tient dans le budget memoire du moment. Cet outil les planifie, les parcourt, agrege, et ecrit un
recensement reutilisable par le labo.

DEUX MODES :

  --plan        n'ouvre AUCUN shard : dit combien de galeries, de quelle duree, et verifie la
                couverture (zero trou, zero recouvrement). Gratuit, instantane.

  --recenser    parcourt reellement chaque galerie en FLUX (memoire plate) et publie, par famille :
                lignes lues, coins distincts, jours couverts, lignes NON DATABLES, bornes reelles.
                SHA-256 verifie (une fois par shard et par processus), Ctrl+C sans perte.

Le recensement est la carte de la mine : il dit a une etude quelle fenetre demander pour obtenir ce
dont elle a besoin, au lieu d'avaler le corpus et d'etre tronquee.

PAPER / LECTURE SEULE : aucun ordre, aucune signature, aucune ecriture dans les shards.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import coffre_tranches as TR          # noqa: E402
from hl_observer.backtesting import plan_de_fouille as PF          # noqa: E402

INDEX_RELPATH = Path("runtime") / "coffre_certifie" / "LOCAL_INDEX.json"
RECENSEMENT_RELPATH = Path("runtime") / "coffre_certifie" / "FOUILLE_RECENSEMENT.json"
JOURNAL_RELPATH = Path("runtime") / "reports" / "fouille" / "journal_galeries.jsonl"

#: Familles du replay PnL (fills + carnets) : le coeur de la chaine causale Copy-Vault.
FAMILLES_REPLAY = ("fills_forward", "fills_backfill", "snapshot", "book_l2", "bbo")


def _lire_index(root: Path) -> list[dict]:
    chemin = root / INDEX_RELPATH
    if not chemin.is_file():
        raise SystemExit(f"index du coffre introuvable : {chemin}")
    index = json.loads(chemin.read_text(encoding="utf-8"))
    shards = index.get("shards") if isinstance(index, dict) else None
    if not isinstance(shards, list) or not shards:
        raise SystemExit("index du coffre vide")
    return [s for s in shards if isinstance(s, dict)]


#: Index du magasin de ticks natifs : verifie par SHA-256 et reference EN PLACE, jamais scelle en
#: shards. Il n'est donc PAS dans LOCAL_INDEX, donc pas atteignable par le pont du labo.
TICKS_RELPATH = Path("runtime") / "coffre_certifie" / "MARKET_TICKS_INDEX.json"

#: Venues autres qu'Hyperliquid : la constitution ferme la famille economique Cross-Venue
#: (`DISABLED_BY_SCOPE`). Leurs ticks sont conserves et verifies, mais les lire pour Copy-Vault
#: rouvrirait par un chemin detourne un scope ferme — exactement le motif qui exclut deja
#: `venue_book` et `venue_dispersion` du pont de replay.
VENUES_HORS_SCOPE = ("binance", "bitget", "bybit", "gate", "okx", "kucoin")


def annexe_ticks(root: Path) -> dict:
    """Ce que contient le magasin de ticks natifs, et pourquoi il n'est PAS dans le plan.

    Un magasin de 56 Go laisse en limbe est pire qu'un magasin exclu : personne ne sait s'il
    s'agit d'un oubli de cablage ou d'une decision. On le classe donc, flux par flux.
    """
    chemin = root / TICKS_RELPATH
    if not chemin.is_file():
        return {"present": False}
    try:
        index = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"present": False, "raison": "INDEX_ILLISIBLE"}
    flux = index.get("par_flux") if isinstance(index, dict) else None
    if not isinstance(flux, list):
        return {"present": False, "raison": "SANS_DETAIL_PAR_FLUX"}
    classes: dict[str, dict] = {}
    for f in flux:
        if not isinstance(f, dict):
            continue
        source = str(f.get("source") or "")
        evenements = int(f.get("evenements") or 0)
        octets = int(f.get("octets") or 0)
        if evenements == 0 and octets == 0:
            motif = "VIDE_AUCUNE_OBSERVATION"
        elif any(v in source.lower() for v in VENUES_HORS_SCOPE):
            motif = "DISABLED_BY_SCOPE:cross_venue"
        else:
            motif = "HYPERLIQUID_NATIF_NON_SCELLE"
        bloc = classes.setdefault(motif, {"flux": 0, "evenements": 0, "octets": 0, "sources": []})
        bloc["flux"] += 1
        bloc["evenements"] += evenements
        bloc["octets"] += octets
        if evenements and f"{source}/{f.get('canal')}" not in bloc["sources"]:
            bloc["sources"].append(f"{source}/{f.get('canal')}")
    return {
        "present": True,
        "shards_verifies": int(index.get("shards_verifies") or 0),
        "octets_verifies": int(index.get("octets_verifies") or 0),
        "anomalies": int(index.get("anomalies") or 0),
        "complet": bool(index.get("complet")),
        "par_motif": classes,
    }


def afficher_annexe(annexe: dict) -> None:
    if not annexe.get("present"):
        return
    print("  ANNEXE — MAGASIN DE TICKS NATIFS (verifie en place, HORS de LOCAL_INDEX)")
    print(f"  {annexe['shards_verifies']:,} shards | "
          f"{annexe['octets_verifies'] / 1e9:.2f} Go | anomalies {annexe['anomalies']}")
    for motif, bloc in sorted(annexe["par_motif"].items(), key=lambda kv: -kv[1]["evenements"]):
        print(f"    {motif:<32} {bloc['flux']:>3} flux  {bloc['evenements']:>13,} evenements  "
              f"{bloc['octets'] / 1e9:>6.2f} Go")
    hl = annexe["par_motif"].get("HYPERLIQUID_NATIF_NON_SCELLE")
    if hl:
        print("    -> la part Hyperliquid est deja presente au coffre sous forme SCELLEE et reduite")
        print("       (famille `bbo`, qui porte deja connection_id et event_id). Son seul apport")
        print("       serait gap_count et local_monotonic_ns : a sceller SI une etude les exige.")
    print()


def _horodate(ms: int | None) -> str:
    if not ms:
        return "-"
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%d/%m %H:%M")


def _jour(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d")


def mesurer_galerie(root: Path, shards: list[dict], familles: list[str],
                    galerie: dict, *, coins: list[str] | None) -> dict:
    """Recense UNE galerie en flux : rien n'est accumule hors des agregats.

    Les cles respectent le contrat de `plan_de_fouille.agreger` : entiers sommes, histogrammes
    fusionnes, listes unies. Aucune moyenne n'est publiee ici — une moyenne de galeries de tailles
    differentes serait un faux.
    """
    debut, fin = int(galerie["debut_ms"]), int(galerie["fin_ms"])
    lignes_lues = 0
    sans_horloge = 0
    shards_lus = 0
    refuses: list[str] = []
    par_famille: dict[str, int] = {}
    par_jour: dict[str, int] = {}
    vus_coins: set[str] = set()
    borne_min: int | None = None
    borne_max: int | None = None
    for famille in familles:
        sel = TR.selectionner(shards, famille=famille, coins=coins, debut_ms=debut, fin_ms=fin)
        if not sel["retenus"]:
            continue
        compteurs: dict = {}
        for ligne in TR.flux(root, sel["retenus"], famille=famille, coins=coins,
                             debut_ms=debut, fin_ms=fin, compteurs=compteurs):
            lignes_lues += 1
            par_famille[famille] = par_famille.get(famille, 0) + 1
            instant = TR.instant_de(ligne, famille)
            if instant is not None:
                par_jour[_jour(instant)] = par_jour.get(_jour(instant), 0) + 1
                borne_min = instant if borne_min is None else min(borne_min, instant)
                borne_max = instant if borne_max is None else max(borne_max, instant)
            coin = ligne.get("coin")
            if isinstance(coin, str) and coin and len(vus_coins) < 5_000:
                vus_coins.add(coin)
        sans_horloge += int(compteurs.get("lignes_sans_horloge", 0))
        shards_lus += int(compteurs.get("shards_lus", 0))
        for r in compteurs.get("shards_refuses", ()):
            refuses.append(f"{famille}:{r.get('motif')}")
    mesure = {
        "lignes_lues": lignes_lues,
        "lignes_sans_horloge": sans_horloge,
        "shards_lus": shards_lus,
        "lignes_par_famille": par_famille,
        "lignes_par_jour": par_jour,
        "coins": sorted(vus_coins),
        "shards_refuses": sorted(set(refuses)),
    }
    if borne_min is not None:
        mesure["instant_min"] = borne_min
        mesure["instant_max"] = borne_max
    return mesure


def afficher_plan(plan: dict, controle: dict, budget: dict) -> None:
    print()
    print("  PLAN DE FOUILLE")
    print(f"  familles      : {len(plan['familles'])} — {', '.join(plan['familles'][:8])}"
          f"{' ...' if len(plan['familles']) > 8 else ''}")
    print(f"  budget        : {plan['budget']:,} lignes par galerie "
          f"(RAM {budget['niveau_ram']}, {budget['dispo_octets'] / 1e9:.1f} Go libres, "
          f"facteur {budget['facteur_ampleur']:.0%})")
    print(f"  corpus        : {plan.get('lignes_indexees', 0):,} lignes indexees sur "
          f"{plan.get('shards_concernes', 0):,} shards")
    fen = plan.get("fenetre_ms") or [None, None]
    print(f"  fenetre       : {_horodate(fen[0])} -> {_horodate(fen[1])}")
    print(f"  galeries      : {len(plan['galeries'])}  "
          f"(estimation {plan['lignes_estimees']:,} lignes)")
    etat = "COMPLETE" if controle["complete"] else "INCOMPLETE"
    print(f"  couverture    : {etat} — trous {len(controle['trous'])}, "
          f"recouvrements {len(controle['recouvrements'])}, "
          f"depassements {len(controle['depassements'])}, "
          f"indivisibles {len(controle['indivisibles'])}, "
          f"shards sans bornes {controle['sans_bornes']}")
    print()
    gals = plan["galeries"]
    apercu = gals if len(gals) <= 12 else gals[:6] + [None] + gals[-5:]
    print(f"  {'#':>4}  {'debut':>12}  {'fin':>12}  {'duree':>10}  {'lignes est.':>12}")
    for g in apercu:
        if g is None:
            print(f"  {'...':>4}")
            continue
        print(f"  {g['rang']:>4}  {_horodate(g['debut_ms']):>12}  {_horodate(g['fin_ms']):>12}  "
              f"{g['duree_ms'] / 3_600_000:>8.2f} h  {g['lignes_estimees']:>12,}"
              f"{'  INDIVISIBLE' if g.get('indivisible') else ''}")
    print()
    if not controle["complete"]:
        print("  ECHEC VISIBLE — la couverture n'est pas complete, le plan ne doit pas etre parcouru.")


def afficher_recensement(resultat: dict) -> None:
    total = resultat["total"]
    print()
    print("  RECENSEMENT")
    print(f"  etat          : {resultat['etat']}  "
          f"({resultat['galeries_faites']} faites, {resultat['galeries_reprises']} reprises, "
          f"{resultat['galeries_restantes']} restantes)")
    ecart = resultat["ecart_estimation"]
    note = "" if ecart is None else f", ecart {ecart:+.2%}"
    print(f"  lignes lues   : {resultat['lignes_lues']:,} "
          f"(estimees {resultat['lignes_estimees']:,}{note})")
    sans = total["sommes"].get("lignes_sans_horloge", 0)
    print(f"  non datables  : {sans:,}")
    jours = total["histogrammes"].get("lignes_par_jour", {})
    print(f"  jours couverts: {len(jours)}")
    print(f"  coins vus     : {total['unions_cardinal'].get('coins', 0)}")
    refuses = total["unions"].get("shards_refuses", [])
    print(f"  refus         : {', '.join(refuses) if refuses else 'aucun'}")
    fam = total["histogrammes"].get("lignes_par_famille", {})
    if fam:
        print()
        print(f"  {'famille':<20} {'lignes lues':>14}")
        for f, n in sorted(fam.items(), key=lambda kv: -kv[1]):
            print(f"  {f:<20} {n:>14,}")
    if total["non_agregeable"]:
        print(f"\n  NON AGREGEABLE (declare, jamais moyenne en silence) : "
              f"{json.dumps(total['non_agregeable'])}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--plan", action="store_true", help="planifier seulement (aucun shard ouvert)")
    p.add_argument("--recenser", action="store_true", help="parcourir toutes les galeries en flux")
    p.add_argument("--familles", default="", help="liste separee par des virgules ; defaut = toutes")
    p.add_argument("--replay", action="store_true", help="raccourci : familles du replay PnL")
    p.add_argument("--coins", default="", help="restreindre a ces coins")
    p.add_argument("--budget", type=int, default=0, help="lignes par galerie ; defaut = RAM libre")
    p.add_argument("--depuis", default="", help="borne basse AAAA-MM-JJ (UTC)")
    p.add_argument("--jusqu", default="", help="borne haute AAAA-MM-JJ (UTC) incluse")
    p.add_argument("--journal", default="", help="journal de reprise ; defaut = runtime/reports")
    p.add_argument("--sortie", default="")
    a = p.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    root = Path(a.root)
    shards = _lire_index(root)
    if a.replay:
        familles = list(FAMILLES_REPLAY)
    elif a.familles.strip():
        familles = [f.strip() for f in a.familles.split(",") if f.strip()]
    else:
        familles = sorted({str(s.get("famille")) for s in shards if s.get("famille")})
    coins = [c.strip() for c in a.coins.split(",") if c.strip()] or None

    def _borne(texte: str, fin_de_journee: bool) -> int | None:
        if not texte.strip():
            return None
        jour = dt.datetime.strptime(texte.strip(), "%Y-%m-%d").replace(tzinfo=dt.UTC)
        if fin_de_journee:
            jour = jour + dt.timedelta(days=1) - dt.timedelta(milliseconds=1)
        return int(jour.timestamp() * 1000)

    budget_mesure = PF.budget_lignes()
    budget = int(a.budget) if a.budget > 0 else budget_mesure["lignes"]
    plan = PF.galeries(shards, familles=familles, budget=budget,
                       debut_ms=_borne(a.depuis, False), fin_ms=_borne(a.jusqu, True), coins=coins)
    controle = PF.couverture(plan)
    afficher_plan(plan, controle, {**budget_mesure, "lignes": budget})
    annexe = annexe_ticks(root)
    afficher_annexe(annexe)
    if a.plan or not a.recenser:
        return 0 if controle["complete"] else 1
    if not controle["complete"]:
        print("  refus de parcourir un plan incomplet.")
        return 1

    journal = Path(a.journal) if a.journal else (root / JOURNAL_RELPATH)
    depart = time.time()
    total_gal = len(plan["galeries"])

    def progression(message: str) -> None:
        ecoule = time.time() - depart
        print(f"    [{ecoule:7.1f}s] {message}", flush=True)

    resultat = PF.parcourir(
        plan,
        lambda g: mesurer_galerie(root, shards, familles, g, coins=coins),
        journal=journal, progress=progression)
    afficher_recensement(resultat)
    charge = {
        "schema": PF.SCHEMA, "genere_ms": int(time.time() * 1000),
        "familles": familles, "coins": coins, "budget": budget,
        "budget_mesure": budget_mesure,
        "galeries_planifiees": total_gal,
        "fenetre_ms": plan.get("fenetre_ms"),
        "couverture": controle,
        "annexe_ticks": annexe,
        "resultat": resultat,
    }
    cible = Path(a.sortie) if a.sortie else (root / RECENSEMENT_RELPATH)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(charge, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  recensement : {cible}")
    print(f"  journal     : {journal}")
    return 0 if resultat["etat"] == "COMPLET" else 130


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  [fouille] Ctrl+C — les galeries terminees sont dans le journal, rien n'est perdu.")
        raise SystemExit(130) from None
