r"""Hypothese L11 — le portage dans le sens du leader (pre-enregistree au §12 du journal).

On copie lentement une OUVERTURE de leader seulement quand le dernier funding publie AVANT l'entree
paie son cote, et on tient H heures. Rendement = prix + funding encaisse sur les heures tenues.

Controles, figes avant la mesure :
  * cout aller-retour affiche a part (frais de la source unique + ecart suppose) ;
  * JUMEAU : meme coin, heure a >= 24 h, MEME condition de portage favorable pour le meme sens,
    mouvement des 72 h precedentes comparable ; meme calcul prix + funding ;
  * retrait du leader le plus favorable ;
  * intervalles par bootstrap de BLOCS de jours.

CAUSALITE. Le taux qui decide est le dernier publie strictement avant l'ouverture de la bougie
d'entree. Le funding compte est celui des heures (entree, entree + H] ; une fenetre ou il manque
plus de 10 % des heures est refusee (NaN), jamais completee.

LECTURE SEULE, EXPLORATION, PAPER. Chaque execution ajoute une ligne au registre chaine.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import goal2_commun as G
import goal2_etude_evenements as E

PASSE_H = 72
JUMEAUX_MIN = 20
COUVERTURE_FUNDING_MIN = 0.9


def series_par_coin(bougies: pd.DataFrame, funding: pd.DataFrame) -> dict[str, dict[str, np.ndarray]]:
    """Par coin : bougies (t, o, c) et funding cumule pour des sommes exactes sur (a, b]."""
    fund = {coin: (g["ts_ms"].to_numpy(np.int64), g["funding"].to_numpy(float))
            for coin, g in funding.sort_values("ts_ms").groupby("coin", sort=False)}
    out = {}
    for coin, b in bougies.sort_values("t_ms").groupby("coin", sort=False):
        if coin not in fund:
            continue
        ft, fr = fund[coin]
        ok = np.isfinite(fr)
        ft, fr = ft[ok], fr[ok]
        out[coin] = {"t": b["t_ms"].to_numpy(np.int64), "o": b["o"].to_numpy(float), "c": b["c"].to_numpy(float),
                     "ft": ft, "fr": fr, "fc": np.concatenate([[0.0], np.cumsum(fr)])}
    return out


def mesures_par_heure(s: dict[str, np.ndarray], h: int) -> dict[str, np.ndarray]:
    """Pour CHAQUE bougie k : dernier funding avant t[k], prix sur h heures, funding sur (t[k], t[k]+h],
    mouvement des PASSE_H heures precedentes."""
    t, o, c, ft, fc = s["t"], s["o"], s["c"], s["ft"], s["fc"]
    n = len(t)
    j_avant = np.searchsorted(ft, t, side="left") - 1          # strictement avant t[k]
    dernier = np.where(j_avant >= 0, s["fr"][np.maximum(j_avant, 0)], np.nan)
    k = np.arange(n)
    j = np.minimum(k + h, n - 1)
    contigu = (k + h < n) & ((t[j] - t) == h * G.HEURE_MS)
    prix = np.where(contigu, o[j] / o - 1.0, np.nan) * 1e4
    a = np.searchsorted(ft, t, side="right")
    b = np.searchsorted(ft, t + h * G.HEURE_MS, side="right")
    somme = fc[b] - fc[a]
    couverture = (b - a) / float(h)
    portage = np.where(contigu & (couverture >= COUVERTURE_FUNDING_MIN), somme * 1e4, np.nan)
    p = np.maximum(k - PASSE_H, 0)
    passe_ok = (k >= PASSE_H) & ((t - t[p]) == PASSE_H * G.HEURE_MS)
    passe = np.where(passe_ok, c[np.maximum(k - 1, 0)] / o[p] - 1.0, np.nan) * 1e4
    return {"dernier": dernier, "prix": prix, "portage": portage, "passe": passe}


def mesurer(ev: pd.DataFrame, series: dict, *, h: int, latence_ms: int, debut: int, fin: int) -> pd.DataFrame:
    lignes = []
    for coin, g in ev.groupby("coin", sort=False):
        s = series.get(coin)
        if s is None:
            continue
        m = mesures_par_heure(s, h)
        t = s["t"]
        dans = (t >= debut) & (t < fin)
        for _, e in g.iterrows():
            instant = int(e["dernier_ms"]) + latence_ms
            k = int(np.searchsorted(t, instant, side="left"))
            if k >= len(t) or t[k] - instant > 2 * G.HEURE_MS:
                continue
            sens = int(e["sens_position"])
            if not np.isfinite(m["dernier"][k]) or -sens * m["dernier"][k] <= 0:
                continue                                       # le funding connu ne paie pas son cote
            total = sens * m["prix"][k] - sens * m["portage"][k]
            if not np.isfinite(total):
                continue
            ligne = {"vault": e["vault"], "coin": coin, "heure": int(t[k] // G.HEURE_MS), "sens": sens,
                     "prix": sens * m["prix"][k], "funding": -sens * m["portage"][k], "total": total}
            m0 = sens * m["passe"][k]
            if np.isfinite(m0):
                idx = np.arange(len(t))
                proches = (dans & np.isfinite(m["passe"]) & (np.abs(idx - k) >= 24)
                           & (-sens * m["dernier"] > 0)
                           & (np.abs(sens * m["passe"] - m0) <= max(20.0, 0.25 * abs(m0))))
                tot_j = sens * m["prix"][proches] - sens * m["portage"][proches]
                tot_j = tot_j[np.isfinite(tot_j)]
                if len(tot_j) >= JUMEAUX_MIN:
                    ligne["jumeau"] = float(tot_j.mean())
                    ligne["exces"] = total - ligne["jumeau"]
            lignes.append(ligne)
    return pd.DataFrame(lignes)


def ic(df: pd.DataFrame, col: str) -> tuple[float, float, float]:
    if df.empty or col not in df:
        return float("nan"), float("nan"), float("nan")
    return G.ic_bootstrap_par_blocs(df[col].to_numpy(float), (df["heure"] // 24).to_numpy())


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--segment", default="exploration", choices=("exploration",))
    p.add_argument("--latence-s", type=int, default=120)
    p.add_argument("--ecart-bps", type=float, default=6.0)
    p.add_argument("--notionnel-min", type=float, default=1000.0)
    p.add_argument("--sans-registre", action="store_true")
    args = p.parse_args(argv)
    debut, fin = G.bornes(args.segment)
    fills = G.charger("fills", args.segment)
    bougies = G.charger("candles_1h", args.segment, marge_avant_ms=4 * G.JOUR_MS, marge_apres_ms=4 * G.JOUR_MS)
    funding = G.charger("funding_1h", args.segment, marge_avant_ms=4 * G.JOUR_MS, marge_apres_ms=4 * G.JOUR_MS)
    ev = E.evenements(fills[fills["coin"].isin(set(bougies["coin"].unique()))])
    ev = ev[ev["ouverture"] & (ev["notionnel"] >= args.notionnel_min)]
    series = series_par_coin(bougies, funding)
    cout = G.frais_aller_retour_bps() + args.ecart_bps
    print(f"  L11 | segment {args.segment} | {len(ev):,} ouvertures >= {args.notionnel_min:,.0f} USD | "
          f"{len(series)} coins avec prix ET funding | cout aller-retour {cout:.1f} bps")
    resultats = {}
    for h in (72, 24):
        df = mesurer(ev, series, h=h, latence_ms=args.latence_s * 1000, debut=debut, fin=fin)
        if df.empty:
            print(f"  {h} h : aucun evenement eligible")
            continue
        df["net"] = df["total"] - cout
        a = {c: ic(df, c) for c in ("prix", "funding", "total", "net")}
        avec_j = df.dropna(subset=["exces"])
        ex = ic(avec_j, "exces")
        contrib = avec_j.groupby("vault")["exces"].sum().sort_values(ascending=False)
        sans = avec_j[avec_j["vault"] != contrib.index[0]] if len(contrib) else avec_j
        ex_sans = ic(sans, "exces")
        print(f"\n  horizon {h} h | n = {len(df)} | {df['vault'].nunique()} leaders | {df['coin'].nunique()} coins"
              f" | avec jumeau : {len(avec_j)}")
        for nom, (m, lo, hi) in a.items():
            print(f"     {nom:<10}{m:>9.1f} bps  [{lo:>7.1f} ; {hi:>7.1f}]")
        print(f"     {'exces':<10}{ex[0]:>9.1f} bps  [{ex[1]:>7.1f} ; {ex[2]:>7.1f}]   (evenement - jumeau)")
        print(f"     exces sans le leader le plus favorable : {ex_sans[0]:.1f} bps [{ex_sans[1]:.1f} ; {ex_sans[2]:.1f}]")
        crit_a = a["net"][1] > 0
        crit_b = ex[1] > 0
        crit_c = ex_sans[1] > 0
        statut = ("CANDIDAT_VALIDATION" if crit_a and crit_b and crit_c
                  else ("PORTAGE_GENERIQUE" if crit_a else "REJECTED"))
        print(f"     criteres : net>0 {crit_a} | exces>0 {crit_b} | sans le meilleur leader {crit_c} -> {statut}")
        resultats[f"{h}h"] = {"n": int(len(df)), "leaders": int(df["vault"].nunique()),
                              **{k: [round(x, 2) for x in v] for k, v in a.items()},
                              "exces": [round(x, 2) for x in ex], "exces_sans_meilleur": [round(x, 2) for x in ex_sans],
                              "statut": statut}
    if not args.sans_registre and resultats:
        G.enregistrer({"hypothese": "L11_portage_dans_le_sens_du_leader", "segment": args.segment,
                       "statut": resultats.get("72h", {}).get("statut", "UNMEASURABLE"),
                       "parametres": {"latence_s": args.latence_s, "ecart_bps": args.ecart_bps,
                                      "notionnel_min": args.notionnel_min, "passe_h": PASSE_H},
                       "cout_aller_retour_bps": cout, "resultats": resultats})
        print(f"\n  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
