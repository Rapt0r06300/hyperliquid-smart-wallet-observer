r"""Placebo de L1 : le rebond apres une position en perte vient-il du LEADER, ou juste du PRIX ?

Une position passe sous l'eau parce que le prix vient de bouger contre elle. Or un prix qui vient
de chuter rebondit souvent tout seul (retour a court terme). Si c'est tout ce qu'on mesure, le
leader n'apporte RIEN : n'importe quelle chute du meme coin ferait pareil.

EPREUVE. Pour chaque evenement reel (coin, heure, sens), on cherche dans le MEME coin toutes les
autres heures du segment ou le mouvement de l'heure precedente etait comparable (meme sens,
meme ampleur a +/- 25 % ou 20 bps), a plus de 24 h de l'evenement. Leur rendement futur moyen
= ce qu'on aurait eu SANS leader. L'exces = evenement - jumeau. C'est l'exces qui est l'apport
du leader ; lui seul compte pour une strategie CopyVault.

Moins de 20 jumeaux -> evenement NON MESURABLE (ecarte, compte et affiche).
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import goal2_commun as G
import goal2_etude_position_en_perte as L1

HORIZONS_H = (1, 2, 4, 8, 24)
JUMEAUX_MIN = 20


def jumeler(ev: pd.DataFrame, bougies: pd.DataFrame, *, debut: int, fin: int, passe_h: int,
            horizons: tuple[int, ...] | None = None) -> pd.DataFrame:
    horizons = horizons or HORIZONS_H
    par_coin = {coin: tuple(b[k].to_numpy() for k in ("t_ms", "o", "c"))
                for coin, b in bougies.sort_values("t_ms").groupby("coin", sort=False)}
    sorties = []
    for coin, g in ev.groupby("coin", sort=False):
        t, o, c = par_coin[coin]
        n = len(t)
        idx = np.arange(passe_h, n)
        # mouvement passe : de l'ouverture de la bougie k-passe_h a la cloture de la bougie k-1
        contigu = (t[idx] - t[idx - passe_h]) == passe_h * G.HEURE_MS
        passe = np.where(contigu, c[idx - 1] / o[idx - passe_h] - 1.0, np.nan) * 1e4
        dans = (t[idx] >= debut) & (t[idx] < fin)
        futur = {}
        for h in horizons:
            j = np.minimum(idx + h, n - 1)
            ok = (idx + h < n) & ((t[j] - t[idx]) == h * G.HEURE_MS)
            futur[h] = np.where(ok, o[j] / o[idx] - 1.0, np.nan) * 1e4
        for _, e in g.iterrows():
            k = int(np.searchsorted(t, e["t_ms"]))
            pos = k - passe_h
            ligne = {"vault": e["vault"], "coin": coin, "seuil": e["seuil"], "t_ms": e["t_ms"],
                     "sens": e["sens"]}
            if pos < 0 or pos >= len(idx) or t[k] != e["t_ms"] or not np.isfinite(passe[pos]):
                sorties.append(ligne)
                continue
            m0 = e["sens"] * passe[pos]
            bande = max(20.0, 0.25 * abs(m0))
            proches = dans & np.isfinite(passe) & (np.abs(e["sens"] * passe - m0) <= bande)
            proches &= np.abs(idx - k) >= 24
            ligne.update({"passe_bps": m0, "jumeaux": int(proches.sum())})
            for h in horizons:
                ligne[f"ev_{h}h"] = e["sens"] * futur[h][pos]
                f = futur[h][proches]
                f = f[np.isfinite(f)]
                ligne[f"ju_{h}h"] = e["sens"] * float(f.mean()) if len(f) >= JUMEAUX_MIN else np.nan
                ligne[f"ex_{h}h"] = ligne[f"ev_{h}h"] - ligne[f"ju_{h}h"]
            sorties.append(ligne)
    return pd.DataFrame(sorties)


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
    p.add_argument("--notionnel-min", type=float, default=1000.0)
    p.add_argument("--seuils", default="-100,-300,100")
    p.add_argument("--passes-h", default="1,4", help="fenetres du mouvement passe servant a l'appariement")
    p.add_argument("--horizons-h", default=",".join(str(h) for h in HORIZONS_H))
    p.add_argument("--sans-registre", action="store_true")
    args = p.parse_args(argv)
    seuils = [int(s) for s in args.seuils.split(",")]
    passes = [int(s) for s in args.passes_h.split(",")]
    horizons = tuple(int(s) for s in args.horizons_h.split(","))
    repere = f"ex_{horizons[0]}h"

    debut, fin = G.bornes(args.segment)
    fills = G.charger("fills", args.segment, marge_avant_ms=400 * G.JOUR_MS)
    bougies = G.charger("candles_1h", args.segment, marge_avant_ms=G.JOUR_MS,
                        marge_apres_ms=4 * G.JOUR_MS)
    fills = fills[fills["coin"].isin(set(bougies["coin"].unique()))]
    fills = fills[~fills["dir"].isin(["Buy", "Sell"])]
    ev, stats = L1.signaux(fills, bougies, debut=debut, fin=fin,
                           latence_ms=args.latence_s * 1000, notionnel_min=args.notionnel_min)
    print(f"  segment {args.segment} | {stats['fills']:,} fills | trous de position : {stats['trous']:,}"
          f" | prix d'entree connu : {100 * stats['fills_prix_connu'] / max(1, stats['fills']):.1f} % des fills")
    ev = ev[ev["seuil"].isin(seuils)]
    enregistres = []
    for passe_h in passes:
        j = jumeler(ev, bougies, debut=debut, fin=fin, passe_h=passe_h, horizons=horizons)
        print(f"\n  === jumeaux apparies sur le mouvement des {passe_h} h precedentes (meme coin, sans leader) ===")
        for seuil in seuils:
            s = j[j["seuil"] == seuil]
            mesurables = s[np.isfinite(s[repere])] if repere in s else s.iloc[0:0]
            nom = f"perte latente <= {seuil}" if seuil < 0 else f"gain latent >= +{seuil}"
            passe_med = float(np.nanmedian(s["passe_bps"])) if "passe_bps" in s and len(s) else float("nan")
            print(f"  {nom} : {len(s)} evenements, {len(mesurables)} mesurables,"
                  f" mouvement passe median {passe_med:.0f} bps (dans le sens de la position)")
            jours = (mesurables["t_ms"] // G.JOUR_MS).to_numpy()
            enreg = {"seuil_bps": seuil, "passe_h": passe_h, "n": int(len(s)), "mesurables": int(len(mesurables))}
            for h in horizons:
                e_m = float(np.nanmean(mesurables[f"ev_{h}h"])) if len(mesurables) else float("nan")
                j_m = float(np.nanmean(mesurables[f"ju_{h}h"])) if len(mesurables) else float("nan")
                x, a, b = G.ic_bootstrap_par_blocs(mesurables[f"ex_{h}h"].to_numpy(), jours)
                enreg[f"{h}h"] = {"evenement": round(e_m, 2), "jumeau": round(j_m, 2),
                                  "exces": round(x, 2), "ic95": [round(a, 2), round(b, 2)]}
                par_leader = mesurables.groupby("vault")[f"ex_{h}h"].agg(["count", "mean"])
                assez = par_leader[par_leader["count"] >= 3]
                meme = int((np.sign(assez["mean"]) == np.sign(x)).sum())
                sans = [float(np.nanmean(mesurables.loc[mesurables["vault"] != v, f"ex_{h}h"]))
                        for v in par_leader.index] if len(par_leader) > 1 else [float("nan")]
                pire = min(sans, key=lambda v: np.sign(x) * v)
                enreg[f"{h}h"].update({"meme_signe": [meme, int(len(assez))], "pire_sans_un_leader": round(pire, 2)})
                print(f"     {h:>2} h   evenement {e_m:>7.1f}   jumeau sans leader {j_m:>7.1f}"
                      f"   EXCES {x:>7.1f} [{a:>7.1f};{b:>7.1f}]   meme signe {meme}/{len(assez)}"
                      f"   sans le leader le plus favorable {pire:>7.1f}")
            enregistres.append(enreg)
    if not args.sans_registre:
        G.enregistrer({"hypothese": "L1_placebo_jumeaux_sans_leader", "segment": args.segment,
                       "statut": "EXPLORATION", "parametres": {
                           "latence_s": args.latence_s, "seuils_bps": seuils, "jumeaux_min": JUMEAUX_MIN,
                           "passes_h": passes, "horizons_h": list(horizons)},
                       "resultats": enregistres})
        print(f"\n  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
