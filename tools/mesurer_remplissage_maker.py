#!/usr/bin/env python3
"""Mesure le TAUX DE REMPLISSAGE MAKER sur les rubans réels — le chiffre qui manquait.

`robustness.maker_adjust_net` et `microstructure_extras.maker_queue_fill_prob` prennent tous deux
le `fill_rate` EN PARAMÈTRE. Personne ne l'avait jamais mesuré, d'où `maker_fill_proven: False`
codé en dur et des clés nommées `..._unproven_fill`. Cet outil produit le chiffre manquant.

CE QU'IL LIT (lecture seule, coût borné : seule la QUEUE de chaque ruban est lue) :
  runtime/data/vault_fills_live.jsonl    — les signaux des leaders
  runtime/data/copy_vault_l2_tape.jsonl  — les carnets
  runtime/data/copy_vault_trades_lane.jsonl — les trades du marché

MÉTHODE. Pour chaque fill de leader, on simule un ordre PASSIF posé au touch du même côté, au
moment où nous l'observons (délai de copie compris), et on regarde si le marché l'aurait consommé
dans l'horizon. Trois choix rendent la mesure honnête plutôt que flatteuse : on se met DERNIER
dans la file, seul le volume au prix OU MIEUX compte, et tout cas douteux sort en NON MESURABLE
sans entrer dans aucun numérateur.

PAPER / lecture seule : aucune requête réseau, aucun ordre, aucune écriture.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))

FILLS = Path("runtime") / "data" / "vault_fills_live.jsonl"
CARNETS = Path("runtime") / "data" / "copy_vault_l2_tape.jsonl"
TRADES = Path("runtime") / "data" / "copy_vault_trades_lane.jsonl"

OCTETS_FILLS = 2 * 1024 * 1024
OCTETS_CARNETS = 24 * 1024 * 1024
OCTETS_TRADES = 48 * 1024 * 1024

#: Délai de copie : on n'observe pas le fill du leader à l'instant où il se produit.
DELAI_COPIE_MS = 60_000
#: Horizon pendant lequel l'ordre passif reste posé.
HORIZON_MS = 30_000


def queue_jsonl(chemin: Path, octets: int) -> list[dict]:
    try:
        taille = chemin.stat().st_size
        depart = max(0, taille - max(1, int(octets)))
        with chemin.open("rb") as flux:
            flux.seek(depart)
            brut = flux.read()
    except OSError:
        return []
    lignes = brut.decode("utf-8", errors="replace").splitlines()
    if depart > 0 and lignes:
        lignes = lignes[1:]
    objets = []
    for ligne in lignes:
        texte = ligne.strip()
        if not texte.startswith("{"):
            continue
        try:
            objet = json.loads(texte)
        except ValueError:
            continue
        if isinstance(objet, dict):
            objets.append(objet)
    return objets


def _ts(enregistrement: dict) -> int | None:
    for cle in ("received_at_ms", "ts_ms", "time", "ts_ex"):
        valeur = enregistrement.get(cle)
        if valeur is None:
            continue
        try:
            return int(valeur)
        except (TypeError, ValueError):
            continue
    return None


def _par_coin(enregistrements: list[dict]) -> dict[str, list[dict]]:
    groupes: dict[str, list[dict]] = {}
    for item in enregistrements:
        coin = str(item.get("coin") or "")
        ts = _ts(item)
        if not coin or ts is None:
            continue
        copie = dict(item)
        copie["_ts"] = ts
        groupes.setdefault(coin, []).append(copie)
    for liste in groupes.values():
        liste.sort(key=lambda x: x["_ts"])
    return groupes


def _carnet_a(carnets: list[dict], instant: int) -> dict | None:
    """Dernier carnet connu AU PLUS TARD à `instant` — jamais un carnet du futur."""
    candidat = None
    for carnet in carnets:
        if carnet["_ts"] <= instant:
            candidat = carnet
        else:
            break
    return candidat


def serie_de_mids(carnets: list[dict]) -> tuple[list[int], list[float]]:
    """(instants, mids) tries — la reference du markout.

    Le mid est (meilleur bid + meilleur ask) / 2 : il ne depend pas du spread, contrairement au
    dernier prix traite, et c'est la convention de toute la litterature de markout.
    """
    points: list[tuple[int, float]] = []
    for carnet in carnets:
        bids, asks = carnet.get("bids5"), carnet.get("asks5")
        if not (isinstance(bids, list) and isinstance(asks, list) and bids and asks):
            continue
        try:
            b, a = float(bids[0][0]), float(asks[0][0])
        except (TypeError, ValueError, IndexError):
            continue
        if a <= b or b <= 0:
            continue
        points.append((int(carnet["_ts"]), (a + b) / 2.0))
    points.sort()
    return [p[0] for p in points], [p[1] for p in points]


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--horizon-ms", type=int, default=HORIZON_MS)
    p.add_argument("--delai-ms", type=int, default=DELAI_COPIE_MS)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.root)

    from hl_observer.backtesting import maker_fill_probe as M

    fills = queue_jsonl(root / FILLS, OCTETS_FILLS)
    carnets = _par_coin(queue_jsonl(root / CARNETS, OCTETS_CARNETS))
    trades = _par_coin(queue_jsonl(root / TRADES, OCTETS_TRADES))
    if not fills or not carnets:
        print("[maker] rubans vides ou absents : rien a mesurer "
              f"({len(fills)} fills, {len(carnets)} coins avec carnets).")
        return 2

    # FENETRE REELLEMENT COUVERTE, PAR COIN. Le ruban des trades pese plusieurs Go : sa queue ne
    # couvre que les dernieres minutes, alors que les fills remontent bien plus loin. Juger un fill
    # dont la fenetre d'observation n'est pas couverte par les trades ferait sortir « aucun trade »
    # — un artefact de LECTURE, pas une information sur le marche. (Meme piege que la
    # reconciliation des carnets, ou une fenetre GLOBALE accusait a tort 114 fills sur 687.)
    couverture = {
        coin: (liste[0]["_ts"], liste[-1]["_ts"])
        for coin, liste in trades.items() if liste
    }

    series = {c: serie_de_mids(liste) for c, liste in carnets.items()}
    cas: list[dict] = []
    economies: list[float] = []
    hors_couverture = 0
    for fill in fills:
        coin = str(fill.get("coin") or "")
        ts = _ts(fill)
        if not coin or ts is None or coin not in carnets:
            cas.append({"verdict": M.NON_MESURABLE, "motif": M.SANS_CARNET})
            continue
        signe = fill.get("signe")
        try:
            cote = M.ACHAT if int(signe) > 0 else M.VENTE
        except (TypeError, ValueError):
            cas.append({"verdict": M.NON_MESURABLE, "motif": M.COTE_INCONNU})
            continue
        instant = ts + int(args.delai_ms)
        fenetre = couverture.get(coin)
        if fenetre is None or not (fenetre[0] <= instant and instant + int(args.horizon_ms) <= fenetre[1]):
            hors_couverture += 1
            continue
        carnet = _carnet_a(carnets[coin], instant)
        if carnet is None:
            cas.append({"verdict": M.NON_MESURABLE, "motif": M.SANS_CARNET})
            continue
        # On poste au TOUCH de notre cote : on achete au meilleur bid, on vend au meilleur ask.
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
        # Gain de spread REEL sur ce carnet, pour remplacer le `spread_saving_usd=0.20`
        # en dur de l'appel historique. Mesure par coin, pas une constante globale.
        if prix is not None and taille > 0:
            gain = M.economie_de_spread(carnet, notionnel=abs(prix * taille))
            if gain is not None:
                economies.append(gain)
        resultat = M.sonder_un_cas(carnet=carnet, trades=trades.get(coin, []),
                                   prix_passif=prix, cote=cote, debut_ms=instant,
                                   horizon_ms=int(args.horizon_ms), taille_voulue=taille)
        resultat["_coin"] = coin
        cas.append(resultat)

    # MARKOUT : ce que les remplissages coutent APRES le fill. Sans lui, on ne mesure que la
    # moitie favorable de `net = capture + adverse - frais`.
    from hl_observer.backtesting import markout as MK

    horizons = [1_000, 5_000, 10_000, 30_000]
    resultats_markout = []
    for item in cas:
        if item.get("verdict") != M.REMPLI:
            continue
        instant = item.get("instant_remplissage_ms")
        coin = item.get("_coin")
        if instant is None or coin is None:
            continue
        instants_c, mids_c = series.get(coin, ([], []))
        if not instants_c:
            continue
        resultats_markout.append(MK.markout_d_un_fill(
            prix_fill=item.get("prix_passif"), cote=item.get("cote"),
            instant_ms=int(instant), instants=instants_c, mids=mids_c,
            horizons_ms=horizons, peremption_ms=60_000))
    mk = MK.agreger(resultats_markout, horizons_ms=horizons, frais_bps=0.0)

    resume = M.taux_de_remplissage(cas)
    resume["markout"] = mk
    resume["signaux"] = len(fills)
    resume["hors_couverture_trades"] = hors_couverture
    if economies:
        economies.sort()
        milieu = economies[len(economies) // 2]
        resume["economie_spread_mediane_usd"] = milieu
        resume["economie_spread_cas"] = len(economies)
    else:
        resume["economie_spread_mediane_usd"] = None
        resume["economie_spread_cas"] = 0
    resume["coins_avec_carnets"] = len(carnets)
    resume["coins_avec_trades"] = len(trades)
    resume["horizon_ms"] = int(args.horizon_ms)
    resume["delai_ms"] = int(args.delai_ms)

    if args.json:
        print(json.dumps(resume, ensure_ascii=False, indent=1))
        return 0

    print("TAUX DE REMPLISSAGE MAKER — mesure, plus hypothese")
    print("=" * 70)
    print(f"  {len(fills)} signaux | {len(carnets)} coins avec carnets | "
          f"{len(trades)} coins avec trades")
    print(f"  {hors_couverture} signaux ECARTES : hors de la fenetre couverte par les trades "
          f"(artefact de lecture, pas une information)")
    print(f"  ordre passif au touch, delai de copie {args.delai_ms // 1000} s, "
          f"horizon {args.horizon_ms // 1000} s")
    print()
    print(f"  {M.lecture(resume)}")
    if resume.get("economie_spread_mediane_usd") is not None:
        print(f"  economie de spread MESUREE (mediane) : "
              f"{resume['economie_spread_mediane_usd']:.4f} USD par entree "
              f"sur {resume['economie_spread_cas']} carnets")
        print("    (l'appel historique utilisait 0,20 USD EN DUR, toutes tailles et coins confondus)")
    if resume["par_motif"]:
        print()
        print("  Non mesurables, par motif :")
        for motif, nombre in resume["par_motif"].items():
            print(f"    {nombre:>6} x {motif}")
    print()
    print("MARKOUT — ce que les remplissages coutent APRES le fill")
    print(f"  {mk['lecture']}")
    print("  reference litterature (Hyperliquid, 125,8 M de remplissages, meme hypothese de file) :")
    print("    capture +0,56 bp | derive 10 s -1,02 bp | net -0,46 bp AVANT frais")
    print()
    print("  Hypotheses PESSIMISTES assumees : on est DERNIER dans la file, et seul le volume")
    print("  au prix OU MIEUX la consomme. Le vrai taux ne peut qu'etre SUPERIEUR a celui-ci.")
    print("  Ce chiffre alimente `maker_adjust_net(fill_rate=...)`, qui etait jusqu'ici devine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
