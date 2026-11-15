#!/usr/bin/env python3
"""L'experience qui tranche le maker — sur le COFFRE CERTIFIE, et sur les DEUX places de file.

POURQUOI SUR LE COFFRE. Les premieres mesures lisaient la QUEUE des rubans vivants : des fenetres
de ~28 minutes et 236 remplissages. Le coffre certifie contient 289 shards de fills (1,2 Go),
234 de micro_bbo (919 Mo), 129 de micro_trades, 195 de carnets L2 — et c'est de toute facon le
seul corpus que le labo lit. Mesurer ailleurs, c'etait mesurer a cote.

POURQUOI LES DEUX BRAS. Le markout mesure sur nos donnees donnait **-3,42 bp a 10 s** en supposant
la DERNIERE place dans la file. Or la litterature mesure, sur le perp BTC d'Hyperliquid a 5 s :
remplissage maker moyen **-0,48 bp**, mais **premiere place +0,32 bp** — un ecart de ~0,8 bp qui
RETOURNE LE SIGNE. Comparer les deux bras sur les memes signaux est, selon les auteurs eux-memes,
« l'experience qui decide si le signe negatif appartient au fait de coter au touch, ou seulement
au fait d'y coter en dernier ».

ALIGNEMENT TEMPOREL. Les shards portent leur LOT DE SCELLEMENT en prefixe
(`20261114T145006Z_2a34eea4__...`), identique d'une famille a l'autre. On ne lit donc que les lots
PRESENTS DANS TOUTES les familles necessaires : c'est ce qui evite le piege rencontre sur les
rubans vivants, ou les fenetres ne se recouvraient pas et produisaient un « aucun trade observe »
qui n'etait qu'un artefact de lecture.

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
FAMILLES = ("fills_forward", "micro_bbo", "micro_trades", "book_l2")

DELAI_COPIE_MS = 60_000
HORIZON_FILL_MS = 30_000
HORIZONS_MARKOUT = (1_000, 5_000, 10_000, 30_000)
PEREMPTION_MID_MS = 60_000


def lots(dossier: Path) -> dict[str, list[Path]]:
    """Shards groupes par lot de scellement (le prefixe avant `__`)."""
    sortie: dict[str, list[Path]] = defaultdict(list)
    if not dossier.is_dir():
        return sortie
    for fichier in dossier.glob("*.jsonl.gz"):
        prefixe = fichier.name.split("__", 1)[0]
        sortie[prefixe].append(fichier)
    return sortie


def lire(fichiers: list[Path], *, maximum: int) -> list[dict]:
    sortie: list[dict] = []
    for fichier in fichiers:
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
                    if isinstance(objet, dict):
                        sortie.append(objet)
                        if len(sortie) >= maximum:
                            return sortie
        except OSError:
            continue
    return sortie


def _ts(enregistrement: dict) -> int | None:
    for cle in ("received_at_ms", "ts_ms", "exchange_ts_ms", "observed_at_ms", "ts_wall_ms"):
        valeur = enregistrement.get(cle)
        if valeur is None:
            continue
        try:
            return int(valeur)
        except (TypeError, ValueError):
            continue
    return None


def par_coin(enregistrements: list[dict]) -> dict[str, list[dict]]:
    groupes: dict[str, list[dict]] = defaultdict(list)
    for item in enregistrements:
        coin = str(item.get("coin") or "")
        ts = _ts(item)
        if not coin or ts is None:
            continue
        copie = dict(item)
        copie["_ts"] = ts
        groupes[coin].append(copie)
    for liste in groupes.values():
        liste.sort(key=lambda x: x["_ts"])
    return groupes


def mids_depuis_bbo(bbo: list[dict]) -> tuple[list[int], list[float]]:
    """Serie de mids depuis le haut de carnet. Le mid ne depend pas du spread — convention de
    toute la litterature de markout."""
    points: list[tuple[int, float]] = []
    for item in bbo:
        ts = item.get("_ts")
        b = item.get("bid") if item.get("bid") is not None else item.get("best_bid")
        a = item.get("ask") if item.get("ask") is not None else item.get("best_ask")
        try:
            b, a = float(b), float(a)
        except (TypeError, ValueError):
            continue
        if a <= b or b <= 0:
            continue
        points.append((int(ts), (a + b) / 2.0))
    points.sort()
    return [p[0] for p in points], [p[1] for p in points]


def carnet_a(carnets: list[dict], instant: int) -> dict | None:
    candidat = None
    for carnet in carnets:
        if carnet["_ts"] <= instant:
            candidat = carnet
        else:
            break
    return candidat


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--lots", type=int, default=6, help="nombre de lots de scellement a lire")
    p.add_argument("--max-par-famille", type=int, default=400_000)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.root)

    from hl_observer.backtesting import maker_fill_probe as M
    from hl_observer.backtesting import markout as MK

    par_famille = {f: lots(root / SHARDS / f) for f in FAMILLES}
    manquantes = [f for f, v in par_famille.items() if not v]
    if manquantes:
        print(f"[coffre] familles absentes : {', '.join(manquantes)}")
        return 2

    communs = set(par_famille[FAMILLES[0]])
    for famille in FAMILLES[1:]:
        communs &= set(par_famille[famille])
    if not communs:
        print("[coffre] aucun lot de scellement commun aux quatre familles : "
              "fenetres non alignees, mesure impossible.")
        return 2
    retenus = sorted(communs)[-int(args.lots):]

    donnees = {
        famille: lire([f for lot in retenus for f in par_famille[famille][lot]],
                      maximum=int(args.max_par_famille))
        for famille in FAMILLES
    }

    fills = donnees["fills_forward"]
    carnets = par_coin(donnees["book_l2"])
    trades = par_coin(donnees["micro_trades"])
    bbo = par_coin(donnees["micro_bbo"])
    series = {coin: mids_depuis_bbo(liste) for coin, liste in bbo.items()}

    couverture = {c: (l[0]["_ts"], l[-1]["_ts"]) for c, l in trades.items() if l}

    resultats: dict[str, dict] = {}
    for place in (M.DERNIER, M.PREMIER):
        cas: list[dict] = []
        markouts: list[dict] = []
        hors = 0
        for fill in fills:
            coin = str(fill.get("coin") or "")
            ts = _ts(fill)
            if not coin or ts is None or coin not in carnets:
                continue
            try:
                cote = M.ACHAT if int(fill.get("signe")) > 0 else M.VENTE
            except (TypeError, ValueError):
                continue
            instant = ts + DELAI_COPIE_MS
            fenetre = couverture.get(coin)
            if fenetre is None or not (fenetre[0] <= instant
                                       and instant + HORIZON_FILL_MS <= fenetre[1]):
                hors += 1
                continue
            carnet = carnet_a(carnets[coin], instant)
            if carnet is None:
                continue
            niveaux = carnet.get("bids5" if cote == M.ACHAT else "asks5")
            prix = None
            if isinstance(niveaux, list) and niveaux and isinstance(niveaux[0], list):
                try:
                    prix = float(niveaux[0][0])
                except (TypeError, ValueError, IndexError):
                    prix = None
            try:
                taille = abs(float(fill.get("sz") or 0.0))
            except (TypeError, ValueError):
                taille = 0.0
            resultat = M.sonder_un_cas(carnet=carnet, trades=trades.get(coin, []),
                                       prix_passif=prix, cote=cote, debut_ms=instant,
                                       horizon_ms=HORIZON_FILL_MS, taille_voulue=taille,
                                       place=place)
            cas.append(resultat)
            if resultat.get("verdict") == M.REMPLI and resultat.get("instant_remplissage_ms"):
                instants_c, mids_c = series.get(coin, ([], []))
                if instants_c:
                    markouts.append(MK.markout_d_un_fill(
                        prix_fill=prix, cote=cote,
                        instant_ms=int(resultat["instant_remplissage_ms"]),
                        instants=instants_c, mids=mids_c,
                        horizons_ms=list(HORIZONS_MARKOUT),
                        peremption_ms=PEREMPTION_MID_MS,
                        # L'ordre est place a `instant` ; le fill arrive plus tard. Sans cette
                        # distinction, la derive d'attente se replie dans la capture et la fait
                        # sortir NEGATIVE — ce qu'a produit la premiere passe (-6,01 bp).
                        instant_ordre_ms=instant))
        resultats[place] = {
            "remplissage": M.taux_de_remplissage(cas),
            "markout": MK.agreger(markouts, horizons_ms=list(HORIZONS_MARKOUT)),
            "hors_couverture": hors,
        }

    if args.json:
        print(json.dumps(resultats, ensure_ascii=False, indent=1, default=str))
        return 0

    print("MAKER SUR LE COFFRE CERTIFIE — les deux places dans la file")
    print("=" * 76)
    print(f"  {len(retenus)} lot(s) de scellement commun(s) | {len(fills)} fills | "
          f"{len(carnets)} coins avec carnets | {len(series)} coins avec mids")
    print()
    for place in (M.DERNIER, M.PREMIER):
        bloc = resultats[place]
        remplissage = bloc["remplissage"]
        taux = remplissage.get("taux")
        print(f"  --- {place} DANS LA FILE ---")
        print(f"  remplissage : "
              + (f"{taux:.1%} sur {remplissage['jugeables']} cas" if taux is not None
                 else f"NON MESURABLE ({remplissage['non_mesurables']} ecartes)"))
        print(f"  markout     : {bloc['markout']['lecture']}")
        print()
    print("  Reference litterature (perp BTC Hyperliquid, 5 s) :")
    print("    maker moyen -0,48 bp | PREMIERE PLACE +0,32 bp | ecart ~0,8 bp")
    print()
    print("  Si le bras PREMIER reste negatif ici, le signe appartient au fait de coter au touch,")
    print("  pas a la place dans la file — et le maker est refute sur nos donnees, point.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
