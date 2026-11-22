r"""Ingestion des jours GRATUITS de Tardis.dev pour Hyperliquid (1er de chaque mois, sans clé).

    tools\python\python.exe tools\ingerer_tardis_jours_gratuits.py --coins BTC ETH HYPE --jours 2026-05-01 2026-06-01

Tardis capture le WebSocket public d'Hyperliquid et publie, pour le 1er jour de chaque mois, des CSV
gratuits : `incremental_book_L2` (carnet complet en deltas, avec instantanés), `trades` (acheteur et vendeur
depuis le 01/12/2024). Chaque ligne a l'heure de la bourse ET l'heure locale de CAPTURE de Tardis ; l'ordre
des lignes est l'ordre de capture.

Validation en flux (jamais le fichier entier en mémoire) : gzip intact, en-tête attendu, lignes, bornes,
monotonie de l'heure locale, trous de capture > 60 s, et pour le carnet la présence d'un instantané initial
(sans lui, la reconstruction est impossible). Statut au manifeste `runtime/history/tardis/MANIFESTE.json`.
Niveau : jamais SAFE (l'heure de capture est celle de Tardis, pas d'Alina). Lecture seule, aucun ordre.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
import time
from pathlib import Path

import httpx

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = Path("runtime") / "history" / "tardis"
URL = "https://datasets.tardis.dev/v1/hyperliquid/{type}/{a}/{m}/{j}/{coin}.csv.gz"
ENTETES = {"User-Agent": "research-client"}
COLONNES = {
    "trades": ("exchange", "symbol", "timestamp", "local_timestamp", "id", "side", "price", "amount"),
    "incremental_book_L2": ("exchange", "symbol", "timestamp", "local_timestamp", "is_snapshot", "side", "price", "amount"),
}
TROU_US = 60 * 1_000_000


def telecharger(url: str, cible: Path, client: httpx.Client) -> tuple[str, int]:
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_suffix(cible.suffix + ".partiel")
    with client.stream("GET", url, timeout=600, follow_redirects=True) as r:
        if r.status_code == 404:
            return "absent_chez_tardis", 0
        r.raise_for_status()
        attendu = int(r.headers.get("content-length") or 0)
        if cible.exists() and attendu and cible.stat().st_size == attendu:
            return "deja_la", attendu
        with tmp.open("wb") as f:
            for bloc in r.iter_bytes(1 << 20):
                f.write(bloc)
    if attendu and tmp.stat().st_size != attendu:
        tmp.rename(tmp.with_suffix(".tronque"))
        raise ValueError(f"taille {tmp.stat().st_size} != {attendu}")
    os.replace(tmp, cible)
    return "telecharge", cible.stat().st_size


def valider(type_: str, chemin: Path) -> dict:
    motifs: list[str] = []
    lignes, prec, non_monotone, trous, plus_grand_trou = 0, None, 0, 0, 0
    tmin = tmax = None
    instantane_initial = None
    try:
        with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
            lecteur = csv.reader(f)
            entete = tuple(next(lecteur))
            manquantes = [c for c in COLONNES[type_] if c not in entete]
            if manquantes:
                return {"statut": "EXTERNAL_REJECTED", "motifs": [f"colonnes manquantes {manquantes}"], "lignes": 0}
            i_loc, i_ts = entete.index("local_timestamp"), entete.index("timestamp")
            i_snap = entete.index("is_snapshot") if "is_snapshot" in entete else None
            for ligne in lecteur:
                lignes += 1
                loc, ts = int(ligne[i_loc]), int(ligne[i_ts])
                if instantane_initial is None and i_snap is not None:
                    instantane_initial = ligne[i_snap] == "true"
                tmin = ts if tmin is None else min(tmin, ts)
                tmax = ts if tmax is None else max(tmax, ts)
                if prec is not None:
                    if loc < prec:
                        non_monotone += 1
                    elif loc - prec > TROU_US:
                        trous += 1
                        plus_grand_trou = max(plus_grand_trou, loc - prec)
                prec = loc
    except (OSError, EOFError, gzip.BadGzipFile, ValueError, csv.Error) as exc:
        return {"statut": "EXTERNAL_REJECTED", "motifs": [f"lecture : {type(exc).__name__}: {exc}"], "lignes": lignes}
    if lignes == 0:
        motifs.append("fichier vide")
    if non_monotone:
        motifs.append(f"{non_monotone} reculs de l'heure locale de capture")
    if type_ == "incremental_book_L2" and instantane_initial is False:
        motifs.append("pas d'instantané initial : carnet non reconstructible")
    couverture_h = (tmax - tmin) / 3.6e9 if tmin is not None else 0.0
    return {"statut": "EXTERNAL_REJECTED" if motifs else "EXTERNAL_VALIDATED", "motifs": motifs, "lignes": lignes,
            "ts_min_us": tmin, "ts_max_us": tmax, "couverture_h": round(couverture_h, 2),
            "trous_de_capture_60s": trous, "plus_grand_trou_s": round(plus_grand_trou / 1e6, 1),
            # un carnet avec des trous n'est PAS admissible à un replay strict sur ces intervalles
            "replay_strict": "NON_ADMISSIBLE" if (trous or motifs) else "A_VERIFIER_PAR_RECONSTRUCTION"}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--coins", nargs="+", default=["BTC", "ETH", "HYPE"])
    p.add_argument("--jours", nargs="+", default=["2026-05-01", "2026-06-01", "2026-07-01", "2026-08-01"])
    p.add_argument("--types", nargs="+", default=list(COLONNES), choices=list(COLONNES))
    p.add_argument("--max-mo", type=float, default=500.0)
    a = p.parse_args(argv)
    for j in a.jours:
        if not j.endswith("-01"):
            print(f"[REFUS] {j} : seuls les 1ers du mois sont gratuits")
            return 2
    base = Path(a.racine) / DOSSIER
    cm = base / "MANIFESTE.json"
    try:
        manifeste = json.loads(cm.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifeste = {"fichiers": {}}
    total = 0
    with httpx.Client(headers=ENTETES) as client:
        for type_ in a.types:
            for coin in a.coins:
                for j in a.jours:
                    an, mo, jo = j.split("-")
                    url = URL.format(type=type_, a=an, m=mo, j=jo, coin=coin)
                    cle = f"{type_}/{j}/{coin}.csv.gz"
                    cible = base / cle
                    if manifeste["fichiers"].get(cle, {}).get("statut") and cible.exists():
                        continue
                    if total > a.max_mo * 1e6:
                        print(f"  [BUDGET] {cle} non téléchargé")
                        continue
                    try:
                        etat, n = telecharger(url, cible, client)
                    except (httpx.HTTPError, ValueError, OSError) as exc:
                        print(f"  [REFUS] {cle} : {exc}")
                        continue
                    if etat == "absent_chez_tardis":
                        manifeste["fichiers"][cle] = {"statut": "ABSENT_A_LA_SOURCE", "url": url}
                        print(f"  {cle:<40} absent chez Tardis")
                        continue
                    total += n if etat == "telecharge" else 0
                    v = valider(type_, cible)
                    manifeste["fichiers"][cle] = {"url": url, "editeur": "Tardis.dev (jours gratuits)", "octets": n,
                                                  "recupere_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                  "niveau_de_preuve": "RESEARCH_ELIGIBLE ; heure de capture = Tardis, pas Alina",
                                                  **v}
                    print(f"  {cle:<40} {etat:<10} {v['lignes']:>10} lignes | {v.get('couverture_h', 0):5.1f} h"
                          f" | trous>60s {v.get('trous_de_capture_60s', '-')} (max {v.get('plus_grand_trou_s', '-')} s) | {v['statut']}"
                          + (f" {v['motifs']}" if v["motifs"] else ""))
                    base.mkdir(parents=True, exist_ok=True)
                    tmp = cm.with_suffix(".json.tmp")
                    tmp.write_text(json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
                    os.replace(tmp, cm)
    print(f"  téléchargé : {total / 1e6:.1f} Mo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
