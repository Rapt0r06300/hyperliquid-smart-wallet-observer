r"""Hypothese L9 : le CONSENSUS de plusieurs leaders sur un meme coin porte-t-il de l'information ?

Un leader seul ne dit rien (essais 1 a 12). Mais plusieurs leaders INDEPENDANTS qui ouvrent dans
le meme sens sur le meme coin en 24 h, c'est une autre affirmation : l'erreur de chacun se
compense, l'information commune reste. C'est l'argument classique du « smart money consensus ».

SIGNAL (fige avant resultat). Pour chaque coin et chaque heure t : sur les 24 h precedentes
(fills connus a t - latence), on compte les leaders dont les OUVERTURES nettes (Open Long -
Open Short, en USD) depassent +seuil (acheteurs) ou -seuil (vendeurs). Consensus = acheteurs -
vendeurs. Evenement = PREMIERE heure ou |consensus| atteint K, puis 24 h de silence sur ce coin.

EPREUVES des la premiere mesure : derive propre du coin retiree ; JUMEAUX sans leader apparies
sur le mouvement des 24 h precedentes (plusieurs leaders entrent souvent dans un coin QUI BOUGE :
il faut separer leur information de la simple tendance) ; concentration par coin.

LECTURE SEULE, PAPER, exploratoire (bougies horaires).
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import goal2_commun as G
import goal2_placebo_position_en_perte as P

HORIZONS_H = (4, 24, 72)
FENETRE_H = 24


def evenements(fills: pd.DataFrame, bougies: pd.DataFrame, *, debut: int, fin: int,
               latence_ms: int, seuil_usd: float, niveaux: tuple[int, ...]) -> pd.DataFrame:
    f = fills[fills["dir"].isin(["Open Long", "Open Short"])].copy()
    f["usd"] = f["px"] * f["sz"] * np.where(f["dir"] == "Open Long", 1.0, -1.0)
    # premiere bougie dont l'ouverture est >= fill + latence : c'est la que le fill devient connu
    f["dispo"] = -((-(f["ts_ms"] + latence_ms)) // G.HEURE_MS) * G.HEURE_MS
    lignes = []
    par_coin = {coin: b["t_ms"].to_numpy() for coin, b in bougies.sort_values("t_ms").groupby("coin", sort=False)}
    for coin, g in f.groupby("coin", sort=False):
        t = par_coin.get(coin)
        if t is None or len(t) < FENETRE_H + 2:
            continue
        leaders = {v: i for i, v in enumerate(g["vault"].unique())}
        flux = np.zeros((len(t), len(leaders)))
        k = np.searchsorted(t, g["dispo"].to_numpy())
        ok = (k < len(t))
        np.add.at(flux, (k[ok], g["vault"].map(leaders).to_numpy()[ok]), g["usd"].to_numpy()[ok])
        cumul = np.cumsum(flux, axis=0)
        roulant = cumul.copy()
        roulant[FENETRE_H:] = cumul[FENETRE_H:] - cumul[:-FENETRE_H]   # somme des 24 dernieres bougies
        consensus = (roulant >= seuil_usd).sum(axis=1) - (roulant <= -seuil_usd).sum(axis=1)
        dans = (t >= debut) & (t < fin)
        for niveau in niveaux:
            dernier = -10**9
            for i in np.flatnonzero(dans & (np.abs(consensus) >= niveau)):
                if i - dernier < FENETRE_H:          # 24 h de silence apres un evenement
                    continue
                dernier = i
                lignes.append({"vault": "consensus", "coin": coin, "seuil": niveau, "t_ms": int(t[i]),
                               "sens": int(np.sign(consensus[i])), "consensus": int(consensus[i])})
    return pd.DataFrame(lignes)


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--segment", default="exploration", choices=G.SEGMENTS_OUVERTS)
    p.add_argument("--latence-s", type=int, default=120)
    p.add_argument("--seuil-usd", type=float, default=1000.0)
    p.add_argument("--sans-registre", action="store_true")
    args = p.parse_args(argv)
    niveaux = (2, 3, 4)

    debut, fin = G.bornes(args.segment)
    fills = G.charger("fills", args.segment, marge_avant_ms=2 * G.JOUR_MS)
    bougies = G.charger("candles_1h", args.segment, marge_avant_ms=3 * G.JOUR_MS,
                        marge_apres_ms=4 * G.JOUR_MS)
    fills = fills[fills["coin"].isin(set(bougies["coin"].unique()))]
    ev = evenements(fills, bougies, debut=debut, fin=fin, latence_ms=args.latence_s * 1000,
                    seuil_usd=args.seuil_usd, niveaux=niveaux)
    print(f"  segment {args.segment} | {fills['vault'].nunique()} leaders | fenetre {FENETRE_H} h |"
          f" ouverture nette >= {args.seuil_usd:,.0f} USD par leader")
    print(f"  cout aller-retour : {G.frais_aller_retour_bps():.0f} bps de frais + l'ecart")
    if not len(ev):
        print("  aucun evenement de consensus")
        return 0
    j = P.jumeler(ev, bougies, debut=debut, fin=fin, passe_h=FENETRE_H, horizons=HORIZONS_H)
    enregistres = []
    for niveau in niveaux:
        s = j[j["seuil"] == niveau]
        col_ok = "ex_24h" in s
        mes = s[np.isfinite(s["ex_24h"])] if col_ok and len(s) else s.iloc[0:0]
        longs = int((s["sens"] > 0).sum())
        print(f"\n  consensus >= {niveau} leaders : {len(s)} evenements ({longs} longs, {len(s) - longs} shorts),"
              f" {s['coin'].nunique()} coins, {len(mes)} mesurables"
              + (f", mouvement des 24 h precedentes median {np.nanmedian(s['passe_bps']):.0f} bps" if "passe_bps" in s and len(s) else ""))
        enreg = {"niveau": niveau, "n": int(len(s)), "mesurables": int(len(mes))}
        if not len(mes):
            enregistres.append(enreg)
            continue
        jours = (mes["t_ms"] // G.JOUR_MS).to_numpy()
        top = mes["coin"].value_counts()
        print(f"     coin le plus frequent : {top.index[0]} ({100 * top.iloc[0] / len(mes):.0f} % des evenements)")
        for h in HORIZONS_H:
            e, ea, eb = G.ic_bootstrap_par_blocs(mes[f"ev_{h}h"].to_numpy(), jours)
            x, a, b = G.ic_bootstrap_par_blocs(mes[f"ex_{h}h"].to_numpy(), jours)
            ju = float(np.nanmean(mes[f"ju_{h}h"]))
            enreg[f"{h}h"] = {"evenement": round(e, 2), "ic95_evenement": [round(ea, 2), round(eb, 2)],
                              "jumeau": round(ju, 2), "exces": round(x, 2), "ic95_exces": [round(a, 2), round(b, 2)]}
            print(f"     {h:>2} h   evenement {e:>7.1f} [{ea:>7.1f};{eb:>7.1f}]   jumeau sans leader {ju:>7.1f}"
                  f"   EXCES {x:>7.1f} [{a:>7.1f};{b:>7.1f}]")
        enregistres.append(enreg)
    if not args.sans_registre:
        G.enregistrer({"hypothese": "L9_consensus_de_plusieurs_leaders", "segment": args.segment,
                       "statut": "EXPLORATION", "parametres": {
                           "latence_s": args.latence_s, "seuil_usd": args.seuil_usd,
                           "fenetre_h": FENETRE_H, "niveaux": list(niveaux)}, "resultats": enregistres})
        print(f"\n  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
