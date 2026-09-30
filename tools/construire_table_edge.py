#!/usr/bin/env python3
"""Q1 -- Construit la TABLE D'EDGE MESUREE a partir des donnees replay REELLES.

    python tools/construire_table_edge.py [--horizon-s 60] [--min-n 30]

Ce que fait ce script, et rien d'autre :

  1. lit TOUS les `candidates*.jsonl` (le signal, tel que la decision l'a vu) et
     `marks*.jsonl` (le prix, apres) enregistres par les runs ;
  2. pour chaque signal, mesure le MARKOUT REEL : ce que le prix a fait, dans le sens du trade,
     apres H secondes ;
  3. coupe CHRONOLOGIQUEMENT en TRAIN (70 %) / TEST (30 %) ;
  4. construit la table sur le TRAIN seul ;
  5. la VALIDE sur le TEST : quand la table dit « il y a de l'edge », le prix a-t-il suivi ?

Le point 5 est le seul qui compte. Une table validee sur ses propres donnees ne vaut rien : elle
retrouve toujours ce qu'on y a mis. C'est le bug qui produit les « alphas fantomes ».

⚠️ Les runs anterieurs au 2026-07-11 ont `coin=""` (bug connu, corrige le 08/07). Ils sont
ECARTES, et on le DIT -- on ne les fait pas passer pour des donnees valides.

Lecture seule. Aucun ordre, aucune cle, aucune signature.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.edge.measured_edge_table import (  # noqa: E402
    Features,
    Observation,
    construire,
    markout_bps,
    sens_du_trade,
    valider_hors_echantillon,
)

REPLAY = RACINE / "runtime" / "replay"
SORTIE_JSON = RACINE / "data" / "reports" / "table_edge_mesuree.json"
SORTIE_TXT = RACINE / "data" / "reports" / "table_edge_mesuree.txt"

COUT_ALLER_RETOUR_BPS = 12.0   # frais+spread+slippage mesures (cf. CLAUDE.md / autopsie 11/07)


def _lignes(fichier: Path):
    try:
        with fichier.open("r", encoding="utf-8", errors="ignore") as fh:
            for ligne in fh:
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    yield json.loads(ligne)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _tous(motif: str) -> list[Path]:
    if not REPLAY.is_dir():
        return []
    return sorted(REPLAY.rglob(motif))


def charger_marks() -> dict[str, tuple[list[float], list[float]]]:
    """{coin: (timestamps tries, mids)} -- la seule source de verite du prix APRES le signal."""
    brut: dict[str, list[tuple[float, float]]] = {}
    for f in _tous("marks*.jsonl"):
        for d in _lignes(f):
            coin = str(d.get("coin") or "").upper()
            ts = d.get("ts")
            mid = d.get("mid")
            if not coin or ts is None or mid is None:
                continue
            try:
                brut.setdefault(coin, []).append((float(ts), float(mid)))
            except (TypeError, ValueError):
                continue
    out: dict[str, tuple[list[float], list[float]]] = {}
    for coin, paires in brut.items():
        paires.sort()
        out[coin] = ([p[0] for p in paires], [p[1] for p in paires])
    return out


def mid_a(marks: dict[str, tuple[list[float], list[float]]], coin: str, t: float,
          *, tolerance_s: float) -> float | None:
    """Le mid le plus proche APRES `t`, dans la tolerance. Aucune extrapolation.

    On refuse de deviner : si le mark le plus proche est a 5 minutes du moment voulu, la mesure
    n'est pas valide -- on rend None, et l'observation est jetee. Interpoler ici, ce serait
    fabriquer le prix qu'on cherche a mesurer.
    """
    serie = marks.get(coin.upper())
    if not serie:
        return None
    ts, mids = serie
    i = bisect.bisect_left(ts, t)
    if i >= len(ts):
        return None
    if ts[i] - t > tolerance_s:
        return None
    return mids[i]


def charger_observations(horizon_s: float) -> tuple[list[Observation], dict[str, int]]:
    marks = charger_marks()
    obs: list[Observation] = []
    stats = {"lus": 0, "sans_coin": 0, "sans_mid": 0, "sans_sens": 0,
             "pas_de_futur": 0, "retenus": 0}

    for f in _tous("candidates*.jsonl"):
        for d in _lignes(f):
            stats["lus"] += 1
            coin = str(d.get("coin") or "").strip().upper()
            if not coin:
                stats["sans_coin"] += 1          # les runs d'avant le 11/07 (bug coin='')
                continue
            direction = d.get("direction") or d.get("action_type")
            if sens_du_trade(direction) == 0:
                stats["sans_sens"] += 1
                continue
            mid0 = d.get("current_mid") or d.get("leader_reference_price")
            ts = d.get("recorded_at")
            if not mid0 or ts is None:
                stats["sans_mid"] += 1
                continue
            try:
                t0 = float(ts)
                m0 = float(mid0)
            except (TypeError, ValueError):
                stats["sans_mid"] += 1
                continue

            m1 = mid_a(marks, coin, t0 + horizon_s, tolerance_s=max(30.0, horizon_s * 0.5))
            if m1 is None:
                stats["pas_de_futur"] += 1
                continue
            mk = markout_bps(mid_entree=m0, mid_futur=m1, direction=direction)
            if mk is None:
                stats["sans_mid"] += 1
                continue

            obs.append(Observation(
                features=Features(
                    strategie="COPY",
                    coin=coin,
                    direction=str(direction),
                    signal_age_ms=_f(d.get("signal_age_ms")),
                    leader_score=_f(d.get("leader_score")),
                    consensus_wallets=_f(d.get("consensus_wallets")),
                ),
                markout_bps=mk,
                signal_ms=t0 * 1000.0,
            ))
            stats["retenus"] += 1

    obs.sort(key=lambda o: o.signal_ms)
    return obs, stats


def _f(v: object) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _moy(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon-s", type=float, default=60.0)
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--seuil-net-bps", type=float, default=0.0,
                    help="edge NET (brut - couts) au-dela duquel la table dirait OUI")
    args = ap.parse_args()

    lignes: list[str] = []

    def dire(s: str = "") -> None:
        print(s)
        lignes.append(s)

    dire("=" * 78)
    dire(" Q1 -- TABLE D'EDGE MESUREE (horizon %.0f s, min n=%d)" % (args.horizon_s, args.min_n))
    dire("=" * 78)

    obs, stats = charger_observations(args.horizon_s)
    dire("")
    dire("  signaux lus            : %7d" % stats["lus"])
    dire("  ecartes coin='' (bug)  : %7d   <- runs d'avant le 11/07, INUTILISABLES" % stats["sans_coin"])
    dire("  ecartes sans mid       : %7d" % stats["sans_mid"])
    dire("  ecartes sens illisible : %7d" % stats["sans_sens"])
    dire("  ecartes sans futur     : %7d   <- aucun mark a T+%.0fs (on n'extrapole PAS)"
         % (stats["pas_de_futur"], args.horizon_s))
    dire("  >>> OBSERVATIONS       : %7d" % stats["retenus"])

    if stats["retenus"] < 200:
        dire("")
        dire("  !!! MOINS DE 200 OBSERVATIONS. On ne construit RIEN.")
        dire("      Une table sur si peu de donnees serait du bruit deguise en science.")
        SORTIE_TXT.parent.mkdir(parents=True, exist_ok=True)
        SORTIE_TXT.write_text("\n".join(lignes), encoding="utf-8")
        return 2

    # ---------------------------------------------------------------- TRAIN / TEST chronologique
    coupe = int(len(obs) * 0.70)
    train, test = obs[:coupe], obs[coupe:]
    dire("")
    dire("  coupe CHRONOLOGIQUE : train=%d  test=%d (le test est STRICTEMENT posterieur)"
         % (len(train), len(test)))

    table = construire(train, horizon_ms=int(args.horizon_s * 1000), min_echantillons=args.min_n)
    dire("  cellules construites : %d  (construite_jusqu_a_ms=%d)"
         % (len(table.cellules), table.construite_jusqu_a_ms))

    # ---------------------------------------------------------------- LA VALIDATION OOS
    #
    # C'est LE point. La table dit « ce bucket a de l'edge ». Sur le TEST -- qu'elle n'a jamais
    # vu -- le prix a-t-il suivi ? Si non, la table est un alpha fantome, et on le dira.
    dire("")
    dire("-" * 78)
    dire(" VALIDATION HORS-ECHANTILLON -- quand la table dit OUI, que fait le prix ?")
    dire("-" * 78)

    dits_oui: list[float] = []     # markouts REELS des signaux que la table aurait ACCEPTES
    dits_non: list[float] = []     # ... et de ceux qu'elle aurait REFUSES
    refus_faute_de_donnees = 0

    for o in test:
        r = table.chercher(o.features, signal_ms=o.signal_ms)
        if not r.mesure or r.edge_brut_bps is None:
            refus_faute_de_donnees += 1
            continue
        net_predit = r.edge_brut_bps - COUT_ALLER_RETOUR_BPS
        (dits_oui if net_predit > args.seuil_net_bps else dits_non).append(o.markout_bps)

    dire("")
    dire("  signaux de test               : %6d" % len(test))
    dire("  refuses faute de donnees      : %6d  (bucket vide -> NO_TRADE, c'est VOULU)"
         % refus_faute_de_donnees)
    dire("  la table aurait dit OUI       : %6d" % len(dits_oui))
    dire("  la table aurait dit NON       : %6d" % len(dits_non))
    dire("")

    cout = COUT_ALLER_RETOUR_BPS
    if dits_oui:
        brut_oui = _moy(dits_oui)
        net_oui = brut_oui - cout
        dire("  >>> LES 'OUI' : markout REEL moyen = %+7.2f bps  |  net apres %.0f bps de couts = %+7.2f bps"
             % (brut_oui, cout, net_oui))
        gagnants = sum(1 for m in dits_oui if m - cout > 0)
        dire("      winrate net : %.1f %% (%d/%d)"
             % (100.0 * gagnants / len(dits_oui), gagnants, len(dits_oui)))
    else:
        dire("  >>> LES 'OUI' : AUCUN. La table ne trouve d'edge nulle part.")

    if dits_non:
        dire("  >>> LES 'NON' : markout REEL moyen = %+7.2f bps  (net %+7.2f)"
             % (_moy(dits_non), _moy(dits_non) - cout))

    dire("")
    dire("-" * 78)
    dire(" VERDICT")
    dire("-" * 78)
    if not dits_oui:
        dire("  La table mesuree ne trouve AUCUN bucket a edge net positif.")
        dire("  Ce n'est pas un bug : c'est la confirmation, par un 3e chemin, de la preuve du")
        dire("  11/07 (24 133 signaux OOS : -7,97 bps meme a cout ZERO).")
        dire("  Branchee, cette table REFUSE le copy-trading. C'est le comportement CORRECT.")
    else:
        net_oui = _moy(dits_oui) - cout
        if net_oui > 0:
            dire("  Il existe un sous-ensemble a edge net POSITIF hors echantillon (%+.2f bps)." % net_oui)
            dire("  A confirmer avant d'y croire : bootstrap, autre periode, autre horizon.")
        else:
            dire("  La table dit OUI sur %d signaux... et le prix fait %+.2f bps net."
                 % (len(dits_oui), net_oui))
            dire("  L'edge est un MIRAGE D'ENTRAINEMENT : il ne survit pas hors echantillon.")
            dire("  C'est exactement ce que la borne basse + le split devaient attraper.")

    # ---------------------------------------------------------------- LA PURGE DES FANTOMES
    #
    # ON NE LIVRE PAS LA TABLE D'ENTRAINEMENT. Jamais.
    #
    # Elle contient des buckets a edge positif -- et l'analyse ci-dessus vient de montrer qu'ils
    # ne survivent PAS hors echantillon. Ce sont des alphas fantomes : ils existent dans les
    # donnees qui les ont fabriques, et nulle part ailleurs. Les livrer, ce serait remplacer une
    # formule inventee par une formule sur-ajustee. Le meme mensonge, mieux habille.
    #
    # On ne garde que les cellules confirmees sur le TEST, avec les statistiques du TEST.
    dire("")
    dire("-" * 78)
    dire(" PURGE DES ALPHAS FANTOMES -- on ne livre que ce qui SURVIT au hors-echantillon")
    dire("-" * 78)

    table_livree = valider_hors_echantillon(table, test)
    dire("")
    dire("  cellules d'entrainement       : %6d" % len(table.cellules))
    dire("  cellules CONFIRMEES sur test  : %6d" % len(table_livree.cellules))

    survivantes_positives = [
        c for c in table_livree.cellules.values()
        if c.borne_basse_bps - cout > args.seuil_net_bps
    ]
    dire("  ... dont a edge NET positif   : %6d" % len(survivantes_positives))
    for c in sorted(survivantes_positives, key=lambda x: -x.borne_basse_bps)[:10]:
        dire("        %-38s n=%4d  moy=%+7.2f  borne_basse=%+7.2f  net=%+7.2f"
             % (c.cle, c.n, c.moyenne_bps, c.borne_basse_bps, c.borne_basse_bps - cout))

    if not survivantes_positives:
        dire("")
        dire("  AUCUNE cellule ne survit avec un edge net positif.")
        dire("  La table livree AUTORISERA donc... rien. C'est le resultat, pas une panne.")

    SORTIE_JSON.parent.mkdir(parents=True, exist_ok=True)
    SORTIE_JSON.write_text(table_livree.vers_json(), encoding="utf-8")
    (SORTIE_JSON.parent / "table_edge_entrainement.json").write_text(
        table.vers_json(), encoding="utf-8")   # gardee pour l'audit, JAMAIS lue par le moteur
    SORTIE_TXT.write_text("\n".join(lignes), encoding="utf-8")
    dire("")
    dire("  table LIVREE (purgee) : %s" % SORTIE_JSON.relative_to(RACINE))
    dire("  table d'entrainement  : data/reports/table_edge_entrainement.json  (AUDIT SEULEMENT)")
    dire("  rapport               : %s" % SORTIE_TXT.relative_to(RACINE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
