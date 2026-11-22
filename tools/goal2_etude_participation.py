r"""Hypothese L8 — « l'elephant dans la mare » : le flux d'un leader qui pese lourd continue-t-il ?

MECANISME. Un leader qui veut une position importante dans un coin PEU LIQUIDE ne peut pas
l'executer d'un coup : il fractionne son ordre sur des heures (meta-ordre). Deux consequences
connues de la microstructure : le signe du flux est autocorrele (memoire longue des signes,
Lillo-Mike-Farmer), et l'impact croit comme la racine du volume execute. Tant que le meta-ordre
court, le prix derive dans son sens.

POURQUOI UN PETIT COMPTE Y GAGNERAIT. C'est une rente de CAPACITE : un gros suiveur ne peut pas
se glisser dans un coin illiquide sans deplacer lui-meme le prix. Un compte de 100 USD, si. Et
l'effet ne depend pas du TALENT du leader -- c'est de la mecanique de flux -- donc le biais de
survie de l'univers y pese moins que sur une strategie de direction.

MESURE. Par (leader, coin, heure) : flux net signe du leader (achats - ventes, en USD), rapporte
au volume du coin dans la meme heure -> taux de participation. On regarde le rendement FUTUR du
coin dans le sens du flux, par tranche de participation, a 1, 4 et 24 heures.

CONTROLES, des le depart (lecons des essais 1-8) :
  * rendement AJUSTE de la derive propre du coin sur le segment ;
  * intervalle par bootstrap de blocs de jours ;
  * concentration par leader (retrait d'un leader, signes).

CAUSALITE. Entree a l'ouverture de la premiere bougie >= dernier fill de l'heure + latence.
EXPLORATOIRE : bougies horaires, carnet non observe ; les couts d'un coin illiquide sont
SUPERIEURS a l'hypothese par defaut, et c'est dit dans la sortie.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import goal2_commun as G

HORIZONS_H = (1, 4, 24)
TRANCHES = ((0.0, 0.01), (0.01, 0.05), (0.05, 0.15), (0.15, 0.40), (0.40, 9e9))


def flux_horaire(fills: pd.DataFrame) -> pd.DataFrame:
    f = fills[~fills["dir"].isin(["Buy", "Sell"])].copy()
    f["usd"] = f["px"] * f["sz"]
    f["usd_signe"] = f["usd"] * f["signe"]
    f["heure"] = f["ts_ms"] // G.HEURE_MS
    g = f.groupby(["vault", "coin", "heure"], sort=False).agg(
        net=("usd_signe", "sum"), brut=("usd", "sum"), dernier_ms=("ts_ms", "max"),
        agressif=("crossed", "mean"), n=("ts_ms", "size")).reset_index()
    g["sens"] = np.sign(g["net"]).astype(np.int8)
    return g[g["sens"] != 0]


def ajouter_prix(flux: pd.DataFrame, bougies: pd.DataFrame, *, latence_ms: int,
                 debut: int, fin: int) -> pd.DataFrame:
    """Volume du coin dans l'heure, rendements futurs signes, et derive propre du coin."""
    n = len(flux)
    volume = np.full(n, np.nan)
    sorties = {h: np.full(n, np.nan) for h in HORIZONS_H}
    derives = {h: np.full(n, np.nan) for h in HORIZONS_H}
    heures = flux["heure"].to_numpy()
    for coin, idx in flux.groupby("coin", sort=False).indices.items():
        b = bougies[bougies["coin"] == coin].sort_values("t_ms")
        if b.empty:
            continue
        t, o, v, c = (b[k].to_numpy() for k in ("t_ms", "o", "v", "c"))
        # volume en USD de l'heure du flux
        j = np.searchsorted(t, heures[idx] * G.HEURE_MS, side="left")
        juste = (j < len(t)) & (t[np.minimum(j, len(t) - 1)] == heures[idx] * G.HEURE_MS)
        volume[idx] = np.where(juste, v[np.minimum(j, len(t) - 1)] * c[np.minimum(j, len(t) - 1)], np.nan)
        instants = flux["dernier_ms"].to_numpy()[idx] + latence_ms
        i0 = np.searchsorted(t, instants, side="left")
        ok = i0 < len(t)
        k0 = np.minimum(i0, len(t) - 1)
        ok &= np.where(ok, t[k0] - instants <= 2 * G.HEURE_MS, False)
        dans = (t >= debut) & (t < fin)
        for h in HORIZONS_H:
            k1 = np.minimum(i0 + h, len(t) - 1)
            ok1 = ok & (i0 + h < len(t)) & ((t[k1] - t[k0]) == h * G.HEURE_MS)
            sorties[h][idx] = np.where(ok1, 1e4 * (o[k1] / o[k0] - 1.0), np.nan)
            if len(o) > h:
                contigu = ((t[h:] - t[:-h]) == h * G.HEURE_MS) & dans[:-h]
                r = (o[h:] / o[:-h] - 1.0)[contigu]
                derives[h][idx] = 1e4 * float(np.mean(r)) if len(r) else np.nan
    out = flux.copy()
    out["volume_usd"] = volume
    out["participation"] = out["brut"] / out["volume_usd"].where(out["volume_usd"] > 0)
    for h in HORIZONS_H:
        out[f"r_{h}h"] = out["sens"].to_numpy() * sorties[h]
        out[f"a_{h}h"] = out["sens"].to_numpy() * (sorties[h] - derives[h])
    return out


def main(argv: list[str] | None = None) -> int:
    for flux_ in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux_.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--segment", default="exploration", choices=G.SEGMENTS_OUVERTS)
    p.add_argument("--latence-s", type=int, default=120)
    p.add_argument("--brut-min", type=float, default=500.0)
    p.add_argument("--agressif-min", type=float, default=None,
                   help="ne garder que les heures dont la part de fills agressifs >= ce seuil")
    p.add_argument("--sans-registre", action="store_true")
    args = p.parse_args(argv)

    debut, fin = G.bornes(args.segment)
    fills = G.charger("fills", args.segment)
    bougies = G.charger("candles_1h", args.segment, marge_avant_ms=G.JOUR_MS,
                        marge_apres_ms=2 * G.JOUR_MS)
    fills = fills[fills["coin"].isin(set(bougies["coin"].unique()))]
    fx = flux_horaire(fills)
    fx = fx[fx["brut"] >= args.brut_min]
    if args.agressif_min is not None:
        fx = fx[fx["agressif"] >= args.agressif_min]
    fx = ajouter_prix(fx, bougies, latence_ms=args.latence_s * 1000, debut=debut, fin=fin)
    fx = fx[np.isfinite(fx["participation"])]

    print(f"  segment {args.segment} | {len(fx):,} heures-leader-coin (flux brut >= {args.brut_min:,.0f} USD)"
          f" | {fx['vault'].nunique()} leaders | {fx['coin'].nunique()} coins")
    print(f"  participation mediane : {100 * fx['participation'].median():.2f} % du volume horaire du coin")
    print(f"  rendement futur en bps, dans le sens du FLUX, derive propre du coin RETIREE ; [IC95 blocs de jours]")
    print(f"  ⚠ cout aller-retour : {G.frais_aller_retour_bps():.0f} bps de frais + l'ecart, qui GRANDIT quand le coin est illiquide")
    print()
    print(f"  {'participation':<16}{'n':>7}{'lead.':>6}{'coins':>6}   " + "   ".join(f"{str(h) + ' h':>24}" for h in HORIZONS_H))
    lignes = []
    for bas, haut in TRANCHES:
        sous = fx[(fx["participation"] >= bas) & (fx["participation"] < haut)]
        nom = f"{100 * bas:g}–{100 * haut:g} %" if haut < 1e9 else f">= {100 * bas:g} %"
        cellules, enreg = [], {"tranche": nom, "n": int(len(sous)), "leaders": int(sous["vault"].nunique())}
        jours = (sous["heure"] // 24).to_numpy()
        for h in HORIZONS_H:
            m, a, b = G.ic_bootstrap_par_blocs(sous[f"a_{h}h"].to_numpy(), jours)
            cellules.append(f"{m:>8.1f} [{a:>6.1f};{b:>6.1f}]")
            enreg[f"a_{h}h"] = {"moy_bps": round(m, 2), "ic95": [round(a, 2), round(b, 2)]}
        lignes.append(enreg)
        print(f"  {nom:<16}{len(sous):>7}{sous['vault'].nunique():>6}{sous['coin'].nunique():>6}   " + "   ".join(cellules))
    if not args.sans_registre:
        G.enregistrer({"hypothese": "L8_participation_du_leader_dans_le_volume", "segment": args.segment,
                       "statut": "EXPLORATION", "parametres": {
                           "latence_s": args.latence_s, "brut_min": args.brut_min,
                           "agressif_min": args.agressif_min}, "resultats": lignes})
        print(f"\n  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
