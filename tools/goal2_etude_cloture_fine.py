r"""L2-fin : que fait le prix dans les MINUTES qui suivent une cloture en perte agressive ?

L'etude horaire (essai 1) a trouve +9,2 bps a 1 h, mais mesures depuis l'ouverture de l'heure
suivante, ~30 min apres le stop. Ici la resolution est de 5 minutes.

PROTOCOLE (pre-enregistre au journal, section 7, AVANT toute lecture) :
  * `execution_a` (26/10 -> 03/11) : on y cherche l'horizon ;
  * `execution_b` (04/11 -> 12/11) : confirmation. Ce script REFUSE de la lire sans
    `--horizon-fige-min`, et n'affiche alors QUE cet horizon, pour la seule famille pre-enregistree.

Evenement : par (leader, coin, fenetre de 5 min), clotures a PnL realise negatif, part agressive
>= 50 %, notionnel >= seuil. Entree : ouverture de la premiere bougie 5 min >= dernier fill +
latence. Sens : celui de la position fermee. Couts affiches, jamais soustraits en douce.

LECTURE SEULE, PAPER. Ecart acheteur-vendeur SUPPOSE (le carnet n'est lu que si un candidat sort).
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import goal2_commun as G

PAS_MS = 300_000
HORIZONS_MIN = (5, 15, 30, 60)
FAMILLE_PREENREGISTREE = "cloture en PERTE agressive"


def evenements(fills: pd.DataFrame) -> pd.DataFrame:
    f = fills[fills["dir"].isin(["Close Long", "Close Short"])].copy()
    f["notionnel"] = f["px"] * f["sz"]
    f["sens_position"] = np.where(f["dir"].str.endswith("Long"), 1, -1).astype(np.int8)
    f["fenetre"] = f["ts_ms"] // PAS_MS
    f["agressif"] = f["notionnel"] * f["crossed"].fillna(False).astype(float)
    g = f.groupby(["vault", "coin", "fenetre", "sens_position"], sort=False).agg(
        notionnel=("notionnel", "sum"), agressif=("agressif", "sum"), pnl=("closed_pnl", "sum"),
        dernier_ms=("ts_ms", "max")).reset_index()
    g["part_agressive"] = g["agressif"] / g["notionnel"].where(g["notionnel"] > 0)
    return g


def rendements(ev: pd.DataFrame, bougies: pd.DataFrame, *, latence_ms: int) -> pd.DataFrame:
    sorties = {m: np.full(len(ev), np.nan) for m in HORIZONS_MIN}
    par_coin = {coin: (b["t_ms"].to_numpy(), b["o"].to_numpy())
                for coin, b in bougies.sort_values("t_ms").groupby("coin", sort=False)}
    for coin, idx in ev.groupby("coin", sort=False).indices.items():
        serie = par_coin.get(coin)
        if serie is None:
            continue
        t, o = serie
        instants = ev["dernier_ms"].to_numpy()[idx] + latence_ms
        i0 = np.searchsorted(t, instants, side="left")
        k0 = np.minimum(i0, len(t) - 1)
        ok = (i0 < len(t)) & (t[k0] - instants <= 2 * PAS_MS)        # pas de trou avant l'entree
        sens = ev["sens_position"].to_numpy()[idx]
        for m in HORIZONS_MIN:
            n = m * 60_000 // PAS_MS
            k1 = np.minimum(i0 + n, len(t) - 1)
            ok1 = ok & (i0 + n < len(t)) & ((t[k1] - t[k0]) == n * PAS_MS)
            sorties[m][idx] = np.where(ok1, 1e4 * sens * (o[k1] / o[k0] - 1.0), np.nan)
    out = ev.copy()
    for m in HORIZONS_MIN:
        out[f"r_{m}m"] = sorties[m]
    return out


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--segment", default="execution_a", choices=("execution_a", "execution_b"))
    p.add_argument("--horizon-fige-min", type=int, default=None, choices=HORIZONS_MIN,
                   help="OBLIGATOIRE pour execution_b : l'unique horizon fige sur execution_a")
    p.add_argument("--latence-s", type=int, default=120)
    p.add_argument("--ecart-bps", type=float, default=6.0)
    p.add_argument("--notionnel-min", type=float, default=1000.0)
    p.add_argument("--sans-registre", action="store_true")
    args = p.parse_args(argv)
    if args.segment == "execution_b" and args.horizon_fige_min is None:
        print("REFUS : `execution_b` est la moitie de CONFIRMATION. Elle ne se lit qu'avec un horizon"
              " fige d'avance (`--horizon-fige-min`), une seule fois.", file=sys.stderr)
        return 2
    if args.segment == "execution_b" and args.sans_registre:
        print("REFUS : une lecture de la confirmation est TOUJOURS enregistree.", file=sys.stderr)
        return 2

    fills = G.charger("fills", args.segment)
    bougies = G.charger("candles_5m", args.segment, marge_apres_ms=2 * G.HEURE_MS)
    fills = fills[fills["coin"].isin(set(bougies["coin"].unique()))]
    ev = evenements(fills)
    ev = ev[ev["notionnel"] >= args.notionnel_min]
    ev = rendements(ev, bougies, latence_ms=args.latence_s * 1000)
    agr, perte = ev["part_agressive"] >= 0.5, ev["pnl"] < 0
    familles = [(FAMILLE_PREENREGISTREE, perte & agr), ("cloture en PERTE passive", perte & ~agr),
                ("cloture en GAIN agressive", (ev["pnl"] > 0) & agr),
                ("cloture en GAIN passive", (ev["pnl"] > 0) & ~agr)]
    horizons = HORIZONS_MIN
    if args.segment == "execution_b":                     # confirmation : une famille, un horizon
        familles, horizons = familles[:1], (args.horizon_fige_min,)
    cout = G.frais_aller_retour_bps() + args.ecart_bps
    print(f"  segment {args.segment} | {fills['vault'].nunique()} leaders | {len(ev):,} evenements de cloture"
          f" (>= {args.notionnel_min:,.0f} USD) | latence {args.latence_s} s")
    print(f"  cout aller-retour : {cout:.1f} bps (frais {G.frais_aller_retour_bps():.1f} + ecart SUPPOSE {args.ecart_bps:.1f})")
    print("  rendement en bps dans le sens de la POSITION fermee ; [IC95 par blocs de jours]")
    print()
    print(f"  {'famille':<28}{'n':>6}{'lead.':>6}{'coins':>6}  " + "  ".join(f"{str(m) + ' min':>24}" for m in horizons))
    lignes, verdict = [], None
    for nom, masque in familles:
        sous = ev[masque]
        jours = (sous["dernier_ms"] // G.JOUR_MS).to_numpy()
        enreg = {"famille": nom, "n": int(len(sous)), "leaders": int(sous["vault"].nunique()),
                 "jours": int(len(np.unique(jours)))}
        cellules, passe = [], []
        for m in horizons:
            moy, bas, haut = G.ic_bootstrap_par_blocs(sous[f"r_{m}m"].to_numpy(), jours)
            enreg[f"{m}min"] = {"moy_bps": round(moy, 2), "ic95": [round(bas, 2), round(haut, 2)],
                                "n": int(np.isfinite(sous[f"r_{m}m"]).sum())}
            cellules.append(f"{moy:>7.1f} [{bas:>6.1f};{haut:>6.1f}]")
            if moy > cout and bas > 0:
                passe.append(m)
        lignes.append(enreg)
        if nom == FAMILLE_PREENREGISTREE:
            verdict = passe
        print(f"  {nom:<28}{len(sous):>6}{sous['vault'].nunique():>6}{sous['coin'].nunique():>6}  " + "  ".join(cellules))
    print()
    if verdict:
        print(f"  CRITERE PRE-ENREGISTRE : ATTEINT aux horizons {verdict} min (moyenne > {cout:.0f} bps et borne basse > 0)")
    else:
        print(f"  CRITERE PRE-ENREGISTRE : NON ATTEINT (il fallait une moyenne > {cout:.0f} bps avec une borne basse > 0)")
    if not args.sans_registre:
        G.enregistrer({"hypothese": "L2_fin_rebond_a_la_minute_apres_cloture_en_perte_agressive",
                       "segment": args.segment,
                       "statut": "CONFIRMATION" if args.segment == "execution_b" else "EXPLORATION",
                       "parametres": {"latence_s": args.latence_s, "ecart_bps_suppose": args.ecart_bps,
                                      "notionnel_min": args.notionnel_min, "horizons_min": list(horizons)},
                       "cout_aller_retour_bps": cout, "critere_atteint_aux_horizons_min": verdict or [],
                       "resultats": lignes})
        print(f"  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
