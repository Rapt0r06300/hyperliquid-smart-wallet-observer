r"""Un effet d'evenement survit-il aux explications BANALES ? Quatre epreuves, avant d'y croire.

Un chiffre comme « −148 bps a 72 h apres une cloture en perte passive » peut n'etre que :

1. **la tendance du marche** : si les leaders ferment surtout des LONGS pendant une baisse
   generale, le prix « continue » parce que tout baisse. Epreuve : rendement AJUSTE du marche
   (on retire le rendement moyen equipondere de tous les coins sur la meme fenetre), et
   separation longs / shorts — un vrai signal doit vivre des deux cotes ;
2. **un seul leader** : epreuve du retrait d'un leader a la fois, et part du plus gros ;
3. **une seule periode** : moities du segment ;
4. **le hasard des essais multiples** : le compte d'essais du registre est rappele.

Meme causalite que l'etude d'evenements (entree a l'ouverture de la premiere bougie >= dernier
fill + latence). LECTURE SEULE, exploratoire (bougies horaires, carnet non observe).
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import goal2_commun as G
import goal2_etude_evenements as E

FAMILLES = {
    "perte_passive": lambda ev: (~ev["ouverture"]) & (ev["pnl"] < 0) & (ev["part_agressive"] < 0.5),
    "perte_agressive": lambda ev: (~ev["ouverture"]) & (ev["pnl"] < 0) & (ev["part_agressive"] >= 0.5),
    "gain_passive": lambda ev: (~ev["ouverture"]) & (ev["pnl"] > 0) & (ev["part_agressive"] < 0.5),
    "gain_agressive": lambda ev: (~ev["ouverture"]) & (ev["pnl"] > 0) & (ev["part_agressive"] >= 0.5),
    "ouverture_agressive": lambda ev: ev["ouverture"] & (ev["part_agressive"] >= 0.5),
    "ouverture_passive": lambda ev: ev["ouverture"] & (ev["part_agressive"] < 0.5),
}


def rendement_du_marche(bougies: pd.DataFrame) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    """Rendement equipondere du marche, heure par heure, cumule pour chaque horizon.

    Rend (heures triees, {H: rendement de t a t+H en bps}). Equipondere et non pondere par la
    capitalisation : on veut retirer « tout a bouge ensemble », pas reconstituer un indice.
    """
    large = bougies.pivot_table(index="t_ms", columns="coin", values="o", aggfunc="first").sort_index()
    log_r = np.log(large).diff()                       # rendement horaire par coin
    moyen = log_r.mean(axis=1, skipna=True).fillna(0.0).to_numpy()
    heures = large.index.to_numpy()
    cumul = np.concatenate([[0.0], np.cumsum(moyen[1:])])   # cumul[i] = somme jusqu'a l'heure i
    par_h = {}
    for h in E.HORIZONS_H:
        r = np.full(len(heures), np.nan)
        r[: len(heures) - h] = 1e4 * (np.exp(cumul[h:] - cumul[: len(heures) - h]) - 1.0)
        par_h[h] = r
    return heures, par_h


def ajuster(ev: pd.DataFrame, bougies: pd.DataFrame, *, latence_ms: int) -> pd.DataFrame:
    heures, par_h = rendement_du_marche(bougies)
    instants = ev["dernier_ms"].to_numpy() + latence_ms
    i0 = np.searchsorted(heures, instants, side="left")
    ok = i0 < len(heures)
    j0 = np.minimum(i0, len(heures) - 1)
    out = ev.copy()
    for h in E.HORIZONS_H:
        marche = np.where(ok, par_h[h][j0], np.nan)
        out[f"a_{h}h"] = out[f"r_{h}h"] - out["sens_position"].to_numpy() * marche
    return out


def ligne(sous: pd.DataFrame, colonne: str) -> str:
    jours = (sous["heure"] // 24).to_numpy()
    m, bas, haut = G.ic_bootstrap_par_blocs(sous[colonne].to_numpy(), jours)
    n = int(np.isfinite(sous[colonne]).sum())
    return f"{m:>8.1f} [{bas:>7.1f};{haut:>7.1f}]  n={n:<5}"


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--segment", default="exploration", choices=G.SEGMENTS_OUVERTS)
    p.add_argument("--famille", default="perte_passive", choices=sorted(FAMILLES))
    p.add_argument("--horizon-h", type=int, default=72, choices=E.HORIZONS_H)
    p.add_argument("--latence-s", type=int, default=120)
    p.add_argument("--notionnel-min", type=float, default=1000.0)
    p.add_argument("--sans-registre", action="store_true")
    args = p.parse_args(argv)

    fills = G.charger("fills", args.segment)
    bougies = G.charger("candles_1h", args.segment, marge_avant_ms=G.JOUR_MS,
                        marge_apres_ms=4 * G.JOUR_MS)
    fills = fills[fills["coin"].isin(set(bougies["coin"].unique()))]
    ev = E.evenements(fills)
    ev = ev[ev["notionnel"] >= args.notionnel_min]
    ev = E.rendements_futurs(ev, bougies, latence_ms=args.latence_s * 1000)
    ev = ajuster(ev, bougies, latence_ms=args.latence_s * 1000)
    sous = ev[FAMILLES[args.famille](ev)].copy()
    h = args.horizon_h
    brut, adj = f"r_{h}h", f"a_{h}h"

    print(f"  famille `{args.famille}` | segment {args.segment} | horizon {h} h | n = {len(sous)}"
          f" | {sous['vault'].nunique()} leaders | {sous['coin'].nunique()} coins")
    print(f"  bps dans le sens de la POSITION ; [IC95 par blocs de jours]")
    print()
    print(f"  1. tendance du marche")
    print(f"     brut                      {ligne(sous, brut)}")
    print(f"     AJUSTE du marche          {ligne(sous, adj)}")
    for nom, s in (("positions LONGUES", 1), ("positions COURTES", -1)):
        part = sous[sous["sens_position"] == s]
        print(f"     {nom:<25} {ligne(part, adj)}   (ajuste)")
    print()
    print(f"  2. concentration par leader (rendement ajuste)")
    par_leader = sous.groupby("vault")[adj].agg(["count", "mean"]).sort_values("count", ascending=False)
    total = par_leader["count"].sum()
    for v, r in par_leader.head(5).iterrows():
        print(f"     {v[:10]}…  n={int(r['count']):<5} ({100 * r['count'] / total:>4.1f} %)  moy {r['mean']:>8.1f}")
    pires = []
    for v in par_leader.index:
        reste = sous[sous["vault"] != v]
        pires.append((float(np.nanmean(reste[adj])), v))
    pires.sort(key=lambda x: abs(x[0]))
    print(f"     retrait d'un leader : l'effet le plus FAIBLE obtenu = {pires[0][0]:.1f} bps"
          f" (sans {pires[0][1][:10]}…)")
    signe = np.sign(np.nanmean(sous[adj]))
    meme_signe = int((np.sign(par_leader.loc[par_leader['count'] >= 5, 'mean']) == signe).sum())
    assez = int((par_leader["count"] >= 5).sum())
    print(f"     leaders (>= 5 evenements) dont l'effet a le MEME signe : {meme_signe} / {assez}")
    print()
    print(f"  3. stabilite dans le temps (rendement ajuste)")
    mediane = sous["heure"].median()
    print(f"     premiere moitie           {ligne(sous[sous['heure'] <= mediane], adj)}")
    print(f"     seconde moitie            {ligne(sous[sous['heure'] > mediane], adj)}")
    print()
    print(f"  4. essais deja enregistres au registre : {G.nombre_d_essais()}")
    if not args.sans_registre:
        m, bas, haut = G.ic_bootstrap_par_blocs(sous[adj].to_numpy(), (sous["heure"] // 24).to_numpy())
        G.enregistrer({
            "hypothese": f"robustesse_{args.famille}_{h}h", "segment": args.segment,
            "statut": "EXPLORATION",
            "parametres": {"latence_s": args.latence_s, "notionnel_min": args.notionnel_min},
            "n": int(len(sous)), "leaders": int(sous["vault"].nunique()),
            "ajuste_marche_bps": round(m, 2), "ic95": [round(bas, 2), round(haut, 2)],
            "meme_signe_par_leader": [meme_signe, assez],
            "effet_min_au_retrait_d_un_leader_bps": round(pires[0][0], 2),
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
