#!/usr/bin/env python3
"""L'AVANCEMENT DU RATTRAPAGE, consultable a tout moment. Aucune passe n'est lancee ici.

POURQUOI. La passe de rattrapage etait **muette** : verifie le 15/11, **zero octet de sortie en une
heure**, parce que son seul resume arrivait APRES l'epuisement du budget — jusqu'a 8 h plus tard.
Un rattrapage qui ne dit rien pendant huit heures est indistinguable d'un rattrapage MORT, et on ne
peut decider ni d'attendre ni de relancer sans le savoir.

La passe affiche desormais une ligne par coin. Cet outil repond a l'autre besoin : **ou en est-on,
maintenant, sans attendre la prochaine ligne.** Il lit l'etat et le coffre, et ne touche a rien.

CE QU'IL DIT, ET QUI N'EST PAS EVIDENT : le funding peut remonter a trois ans, mais **les bougies
s'arretent a 211 jours** — limite reelle de `candleSnapshot`, pas une borne inventee. La strategie a
besoin des DEUX. L'outil affiche donc separement ce qui est collecte et ce qui est EXPLOITABLE.

PAPER / lecture seule.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import gzip
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
ETAT = Path("runtime") / "data" / "backfill_candles_etat.json"
SHARDS = Path("runtime") / "coffre_certifie" / "local" / "shards"
SERIE = "funding"


def profondeur_depuis_coffre(dossier: Path) -> dict[str, float]:
    """Profondeur REELLE par coin, en jours : `maintenant - heure la plus ANCIENNE presente`.

    Seul le coffre porte cette information. L'etat du collecteur ne stocke que l'heure la plus
    RECENTE, qui mesure le retard et non la profondeur — confondre les deux faisait dire a cet
    outil l'inverse de la verite.
    """
    import time as _t
    maintenant_h = int(_t.time()) // 3600
    plus_ancien: dict[str, int] = {}
    for f in sorted(dossier.glob("*.jsonl.gz")) if dossier.is_dir() else ():
        try:
            with gzip.open(f, "rt", encoding="utf-8", errors="replace") as flux:
                for ligne in flux:
                    if not ligne.strip().startswith("{"):
                        continue
                    try:
                        o = json.loads(ligne)
                    except ValueError:
                        continue
                    coin, t = o.get("coin"), o.get("ts_ms")
                    if not coin or t is None:
                        continue
                    with contextlib.suppress(TypeError, ValueError):
                        h = int(t) // 3_600_000
                        if str(coin) not in plus_ancien or h < plus_ancien[str(coin)]:
                            plus_ancien[str(coin)] = h
        except OSError:
            continue
    return {c: (maintenant_h - h) / 24.0 for c, h in plus_ancien.items()}


def heures_scellees(dossier: Path, cle: str, *, interval: str | None = None) -> set[int]:
    """Heures reellement PRESENTES dans le coffre — la seule chose que le labo lira.

    `interval` est OBLIGATOIRE pour la famille `candle` : elle melange 1 h, 5 m et 1 j, et ces pas
    n'ont pas du tout la meme profondeur (208 jours contre 1 101). Les confondre faisait annoncer
    des bougies « horaires » remontant a 2020.
    """
    out: set[int] = set()
    for f in sorted(dossier.glob("*.jsonl.gz")) if dossier.is_dir() else ():
        try:
            with gzip.open(f, "rt", encoding="utf-8", errors="replace") as flux:
                for ligne in flux:
                    if not ligne.strip().startswith("{"):
                        continue
                    try:
                        o = json.loads(ligne)
                    except ValueError:
                        continue
                    if interval is not None and o.get("interval") != interval:
                        continue
                    t = o.get(cle) or o.get("ts_ms") or o.get("open_ts_ms")
                    if t:
                        with contextlib.suppress(TypeError, ValueError):
                            out.add(int(t) // 3_600_000)
        except OSError:
            continue
    return out


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    args = p.parse_args(argv)
    root = Path(args.root)
    maintenant = int(time.time() * 1000)

    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tools"))
    try:
        from backfill_candles_vaults import (PROFONDEUR_FUNDING_MS, charger_univers,
                                             coins_suivis, filtrer_abonnables)
    except ImportError as exc:
        print(f"[avancement] import impossible : {exc}")
        return 2

    coins, _ = filtrer_abonnables(coins_suivis(root), charger_univers(root))
    try:
        etat = json.loads((root / ETAT).read_text(encoding="utf-8"))
        derniers = etat.get("intervalles", {}).get(SERIE, {}) or {}
    except (OSError, ValueError, AttributeError):
        derniers = {}

    cible_j = PROFONDEUR_FUNDING_MS / 86_400_000
    # 15/11 — CORRECTION D'UN OUTIL QUI MENTAIT. La premiere version calculait
    # `(maintenant - derniers[coin])` en l'appelant « profondeur ». Or `derniers` stocke l'heure la
    # plus RECENTE recuperee : cette difference mesure donc **le RETARD**, exactement l'inverse.
    # Un coin qui venait de demarrer son rattrapage affichait 1 079 jours et paraissait parfait ;
    # un coin a jour affichait 0 et paraissait vide. **Un indicateur qui dit le contraire de ce
    # qu'il annonce est pire qu'absent.**
    # La profondeur REELLE est l'heure la plus ANCIENNE presente, et seul le coffre la porte.
    profondeurs_par_coin = profondeur_depuis_coffre(root / SHARDS / "funding_history")
    profondeurs = [profondeurs_par_coin.get(c, 0.0) for c in coins]
    servis = [x for x in profondeurs if x > 0]
    retards = [((maintenant - int(d)) / 86_400_000) for d in derniers.values() if d]

    print("AVANCEMENT DU RATTRAPAGE DE FUNDING")
    print("=" * 70)
    print(f"  cible : {cible_j:.0f} jours par coin | {len(coins)} coins suivis")
    if not servis:
        print("  aucun coin servi : la passe n'a pas encore tourne.")
        return 0
    servis.sort()
    atteints = sum(1 for x in servis if x >= cible_j * 0.95)
    print(f"  {len(servis)}/{len(coins)} coins ont du funding | "
          f"{atteints} ont atteint la cible")
    print(f"  PROFONDEUR (heure la plus ancienne du coffre) : min {servis[0]:.0f} j | "
          f"mediane {servis[len(servis) // 2]:.0f} j | max {servis[-1]:.0f} j")
    if retards:
        retards.sort()
        print(f"  retard (heure la plus recente) : mediane {retards[len(retards) // 2]:.1f} j "
              "— c'est autre chose, et le confondre faisait mentir cet outil")
    total = sum(servis)
    besoin = len(coins) * cible_j
    print(f"  avancement global : {total / besoin:.1%} "
          f"({total:.0f} jours-coins sur {besoin:.0f})")
    # barre, parce qu'un pourcentage seul se lit mal
    rempli = int(40 * min(1.0, total / besoin))
    print(f"  [{'#' * rempli}{'.' * (40 - rempli)}]")
    print()

    f_h = heures_scellees(root / SHARDS / "funding_history", "ts_ms")
    c_h = heures_scellees(root / SHARDS / "candle", "open_ts_ms", interval="1h")
    c_j = heures_scellees(root / SHARDS / "candle", "open_ts_ms", interval="1d")
    if f_h and c_h:
        commun = f_h & (c_h | c_j)
        jour = lambda h: dt.datetime.utcfromtimestamp(h * 3600).date()
        print("  CE QUI EST COLLECTE, ET CE QUI EST EXPLOITABLE")
        print(f"    funding scelle : {len(f_h):>6} h ({len(f_h) / 24:>5.0f} j) "
              f"du {jour(min(f_h))} au {jour(max(f_h))}")
        print(f"    bougies 1 h    : {len(c_h):>6} h ({len(c_h) / 24:>5.0f} j) "
              f"du {jour(min(c_h))} au {jour(max(c_h))}")
        if c_j:
            print(f"    bougies 1 j    : {len(c_j):>6} j            "
                  f"du {jour(min(c_j))} au {jour(max(c_j))}  <- le pas PROFOND")
        print(f"    **INTERSECTION : {len(commun):>6} h ({len(commun) / 24:>5.0f} j)** "
              "<- la SEULE fenetre que la strategie peut mesurer")
        print()
        print("    Les bougies s'arretent a ~211 jours : c'est une limite REELLE de")
        print("    `candleSnapshot`, pas une borne inventee comme l'etait celle du funding.")
        print("    Le funding plus ancien sert a tester la PERSISTANCE du signal, pas le PnL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
