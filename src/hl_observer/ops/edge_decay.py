"""Edge-decay des wallets : grille complète d'horizons et segmentation par action (lecture seule, 0 réseau).

Conclure « le copy-wallet est mort » sur un seul horizon de 5 s serait une faute de méthode : un edge peut
exister à 250 ms et avoir disparu à 5 s, ou n'apparaître qu'à 60 s. On mesure donc la **courbe** :

    100 / 250 / 500 ms · 1 / 2 / 5 / 10 / 30 / 60 / 120 / 300 s

**Un horizon n'est mesuré que si la bande de prix le permet.** Si la cadence médiane des cotations d'un coin
est de 1,2 s, un markout à 100 ms n'existe pas dans les données : il serait fabriqué par interpolation. Ces
horizons sont déclarés `NON_MESURABLE` par coin et leurs épisodes sont **comptés**, jamais silencieusement
rabattus sur la cotation suivante.

Chaîne mesurée à chaque point : `markout brut → coûts A/R → edge net copiable`.

Segmentations : action (`OPEN/ADD/REDUCE/CLOSE/FLIP`), premier fill d'une séquence vs suivants, wallet.
Aucune promotion n'est possible depuis ce module : il mesure, il ne sélectionne pas.
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from hl_observer.ops.global_observer_pipeline import markout_bps

SCHEMA_VERSION = "hypersmart.edge_decay.v1"
RAPPORT_RELPATH = Path("runtime") / "reports" / "edge_decay.json"

#: Grille PRÉ-ENREGISTRÉE. Fixée avant lecture : on ne choisit pas l'horizon après avoir vu les résultats.
HORIZONS_MS: tuple[int, ...] = (100, 250, 500, 1_000, 2_000, 5_000, 10_000, 30_000, 60_000, 120_000, 300_000)

ACTIONS = ("OPEN", "ADD", "REDUCE", "CLOSE", "FLIP")

#: Un horizon est mesurable si la cadence médiane du coin le permet, avec cette marge.
#: `horizon >= cadence_mediane * FACTEUR` — en deçà, le « markout » ne serait qu'un artefact d'échantillonnage.
FACTEUR_RESOLUTION = 1.0

#: Sous ce nombre d'épisodes, aucune moyenne n'est publiée pour la cellule.
MIN_EPISODES_CELLULE = 20


def cadence_par_coin(index: Mapping[str, Mapping[str, Sequence]]) -> dict[str, float | None]:
    """Cadence MÉDIANE entre deux cotations, par coin. C'est elle qui borne les horizons mesurables."""
    out: dict[str, float | None] = {}
    for coin, bloc in index.items():
        temps = list(bloc.get("ts") or [])
        if len(temps) < 3:
            out[coin] = None
            continue
        deltas = [t2 - t1 for t1, t2 in zip(temps, temps[1:]) if t2 > t1]
        out[coin] = float(statistics.median(deltas)) if deltas else None
    return out


def horizons_mesurables(cadence_ms: float | None, horizons: Iterable[int] = HORIZONS_MS,
                        *, facteur: float = FACTEUR_RESOLUTION) -> list[int]:
    """Horizons réellement observables pour une cadence donnée. Cadence inconnue ⇒ aucun horizon."""
    if cadence_ms is None or cadence_ms <= 0:
        return []
    seuil = float(cadence_ms) * float(facteur)
    return [int(h) for h in horizons if float(h) >= seuil]


def _premier_de_sequence(episodes: Sequence[Mapping[str, Any]]) -> list[bool]:
    """Un fill est « premier de séquence » s'il ouvre la position (OPEN ou FLIP)."""
    return [e.get("action") in {"OPEN", "FLIP"} for e in episodes]


def _agreger(valeurs: Sequence[float], *, cout_ar_bps: float,
             min_episodes: int = MIN_EPISODES_CELLULE) -> dict[str, Any]:
    n = len(valeurs)
    if n < int(min_episodes):
        return {"n": n, "statut": "N_INSUFFISANT", "gross_bps": None, "net_bps": None, "hit_rate": None}
    brut = statistics.mean(valeurs)
    nets = [v - float(cout_ar_bps) for v in valeurs]
    return {"n": n, "statut": "MESURE",
            "gross_bps": round(brut, 4), "gross_median_bps": round(statistics.median(valeurs), 4),
            "net_bps": round(statistics.mean(nets), 4),
            "hit_rate_gross": round(sum(1 for v in valeurs if v > 0) / n, 4),
            "hit_rate_net": round(sum(1 for v in nets if v > 0) / n, 4)}


def grille(episodes_par_wallet: Mapping[str, Sequence[Mapping[str, Any]]],
           index_prix: Mapping[str, Mapping[str, Sequence]], *, cout_ar_bps: float = 9.0,
           horizons: Iterable[int] = HORIZONS_MS,
           min_episodes: int = MIN_EPISODES_CELLULE) -> dict[str, Any]:
    """Grille complète horizon × segmentation. Rend aussi ce qui n'a PAS pu être mesuré, et pourquoi."""
    cadences = cadence_par_coin(index_prix)
    horizons = tuple(int(h) for h in horizons)

    par_horizon: dict[int, list[float]] = {h: [] for h in horizons}
    par_horizon_action: dict[tuple[int, str], list[float]] = {}
    par_horizon_premier: dict[tuple[int, bool], list[float]] = {}
    par_horizon_wallet: dict[tuple[int, str], list[float]] = {}
    non_mesurables: dict[str, int] = {}
    coins_vus: set[str] = set()

    for wallet, episodes in episodes_par_wallet.items():
        premiers = _premier_de_sequence(list(episodes))
        for episode, est_premier in zip(episodes, premiers):
            coin = str(episode.get("coin") or "")
            coins_vus.add(coin)
            cadence = cadences.get(coin.upper())
            ouverts = set(horizons_mesurables(cadence, horizons))
            for h in horizons:
                if h not in ouverts:
                    non_mesurables["HORIZON_SOUS_LA_CADENCE"] = non_mesurables.get(
                        "HORIZON_SOUS_LA_CADENCE", 0) + 1
                    continue
                m = markout_bps(index_prix, coin=coin, ts_ms=episode.get("ts_ms"),
                                sens=episode.get("sens"), horizon_ms=h)
                if m is None:
                    non_mesurables["PRIX_ABSENT_A_LHORIZON"] = non_mesurables.get(
                        "PRIX_ABSENT_A_LHORIZON", 0) + 1
                    continue
                par_horizon[h].append(m)
                action = str(episode.get("action") or "?")
                par_horizon_action.setdefault((h, action), []).append(m)
                par_horizon_premier.setdefault((h, bool(est_premier)), []).append(m)
                par_horizon_wallet.setdefault((h, wallet), []).append(m)

    courbe = {str(h): _agreger(par_horizon[h], cout_ar_bps=cout_ar_bps, min_episodes=min_episodes)
              for h in horizons}
    par_action = {}
    for (h, action), valeurs in sorted(par_horizon_action.items()):
        par_action.setdefault(str(h), {})[action] = _agreger(
            valeurs, cout_ar_bps=cout_ar_bps, min_episodes=min_episodes)
    premier_vs_suite = {}
    for (h, est_premier), valeurs in sorted(par_horizon_premier.items()):
        cle = "premier_de_sequence" if est_premier else "fills_suivants"
        premier_vs_suite.setdefault(str(h), {})[cle] = _agreger(
            valeurs, cout_ar_bps=cout_ar_bps, min_episodes=min_episodes)

    mesures = [(h, c) for h, c in courbe.items() if c["statut"] == "MESURE"]
    positifs = [(h, c) for h, c in mesures if (c["net_bps"] or 0) > 0]
    return {
        "schema_version": SCHEMA_VERSION,
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "cout_ar_bps": float(cout_ar_bps), "min_episodes_cellule": int(min_episodes),
        "horizons_preenregistres_ms": list(horizons),
        "cadence_mediane_ms": {c: cadences.get(c) for c in sorted(coins_vus & set(cadences))},
        "non_mesurables": non_mesurables,
        "courbe_globale": courbe,
        "par_action": par_action,
        "premier_vs_suite": premier_vs_suite,
        "par_wallet": {str(h): {w: _agreger(v, cout_ar_bps=cout_ar_bps, min_episodes=min_episodes)
                                for (hh, w), v in par_horizon_wallet.items() if hh == h}
                       for h in horizons},
        "horizons_mesures": [h for h, _ in mesures],
        "horizons_nets_positifs": [h for h, _ in positifs],
        "verdict": ("AUCUN_HORIZON_NET_POSITIF" if not positifs else "HORIZONS_A_INVESTIGUER"),
        "note": "une cellule positive n'est pas un edge : il lui faut pre-registration, N, placebo, OOS "
                "et forward post-freeze avant toute promotion",
        "promotion_possible": False, "real_execution": False,
    }


def main(argv: Iterable[str] | None = None) -> int:
    from hl_observer.following import fills_sources as FS
    from hl_observer.following import wallet_reconstruction as WR
    from hl_observer.ops.global_observer_pipeline import SOURCES_DEFAUT, PRIX_DEFAUT, charger_prix

    p = argparse.ArgumentParser(description="Grille d'edge-decay des wallets (lecture seule, paper).")
    p.add_argument("--root", default=".")
    p.add_argument("--cout-ar-bps", type=float, default=9.0)
    p.add_argument("--max-lignes-prix", type=int, default=200_000)
    p.add_argument("--min-episodes", type=int, default=MIN_EPISODES_CELLULE)
    a = p.parse_args(list(argv) if argv is not None else None)
    racine = Path(a.root).resolve()

    fills: list[dict[str, Any]] = []
    stats = FS.StatsIngestion()
    for rel, source in SOURCES_DEFAUT:
        fills.extend(FS.flux_fills(racine / rel, source=source, stats=stats))
    reconstruction = WR.reconstruire(fills)
    desync = {d["wallet"] for d in reconstruction.desyncs}
    par_wallet = {w: e for w, e in WR.episodes_par_wallet(reconstruction).items() if w not in desync}
    coins = {e["coin"] for e in reconstruction.episodes}
    index = charger_prix(racine / PRIX_DEFAUT, coins=coins, max_lignes=int(a.max_lignes_prix))

    rapport = grille(par_wallet, index, cout_ar_bps=float(a.cout_ar_bps),
                     min_episodes=int(a.min_episodes))
    rapport["ingestion"] = stats.resume()
    rapport["n_wallets_fiables"] = len(par_wallet)
    chemin = racine / RAPPORT_RELPATH
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")

    print("wallets fiables : %s | cadence mediane (ms) : %s" % (
        rapport["n_wallets_fiables"],
        {k: v for k, v in list(rapport["cadence_mediane_ms"].items())[:4]}))
    print("%-10s %8s %12s %12s %10s" % ("horizon", "n", "gross_bps", "net_bps", "hit_net"))
    for h in rapport["horizons_preenregistres_ms"]:
        c = rapport["courbe_globale"][str(h)]
        print("%-10s %8s %12s %12s %10s" % (h, c["n"], c["gross_bps"], c["net_bps"], c.get("hit_rate_net")))
    print("verdict :", rapport["verdict"], "| horizons nets positifs :", rapport["horizons_nets_positifs"])
    print("rapport :", chemin)
    return 0


__all__ = ["SCHEMA_VERSION", "HORIZONS_MS", "ACTIONS", "FACTEUR_RESOLUTION", "MIN_EPISODES_CELLULE",
           "cadence_par_coin", "horizons_mesurables", "grille", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
