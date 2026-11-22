r"""L12 — la sortie miroir (pré-enregistrée au §14 du journal).

Le suiveur entre 2 min après l'OUVERTURE d'un leader et sort 2 min après la PREMIÈRE clôture du même
côté par ce leader sur ce coin. Diagnostic de départ (§14) : le suiveur entre au même prix à 2 bps
près, mais à horizon fixe il perd le retournement que le leader, lui, évite en sortant.

Jumeau : même coin, même sens, même durée de détention, entrée à >= 24 h de l'événement. Il dit si le
moment choisi par le leader compte, au-delà du coin, du sens et de la durée.

Causalité : chaque prix est l'ouverture d'une bougie 5 min postérieure de 120 s au fill observé.
LECTURE SEULE, EXPLORATION, PAPER. Une ligne au registre chaîné par exécution.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import goal2_commun as G

PAS = 300_000
LATENCE = 120_000
DETENTION_MAX = 7 * G.JOUR_MS
JUMEAUX_MIN = 20
NOTIONNEL_MIN = 1000.0


def apparier_sorties(fills: pd.DataFrame) -> pd.DataFrame:
    """Chaque ouverture -> la première clôture du même côté, même leader, même coin, après elle."""
    f = fills[fills["dir"].isin(["Open Long", "Open Short", "Close Long", "Close Short"])].copy()
    f["cote"] = np.where(f["dir"].str.endswith("Long"), 1, -1)
    f["notionnel"] = f["px"] * f["sz"]
    lignes = []
    for (vault, coin, cote), g in f.sort_values("ts_ms", kind="stable").groupby(["vault", "coin", "cote"], sort=False):
        ouv = g[g["dir"].str.startswith("Open")]
        clo = g[g["dir"].str.startswith("Close")]["ts_ms"].to_numpy()
        for _, e in ouv.iterrows():
            if e["notionnel"] < NOTIONNEL_MIN:
                continue
            j = np.searchsorted(clo, e["ts_ms"], side="right")
            sortie = int(clo[j]) if j < len(clo) else None
            lignes.append({"vault": vault, "coin": coin, "sens": int(cote), "entree_ms": int(e["ts_ms"]),
                           "sortie_ms": sortie})
    return pd.DataFrame(lignes)


def mesurer(ev: pd.DataFrame, bougies: pd.DataFrame, *, debut: int, fin: int) -> pd.DataFrame:
    par = {c: (g["t_ms"].to_numpy(np.int64), g["o"].to_numpy(float))
           for c, g in bougies.sort_values("t_ms").groupby("coin", sort=False)}
    out = []
    for coin, g in ev.groupby("coin", sort=False):
        serie = par.get(coin)
        if serie is None:
            continue
        t, o = serie
        dans = np.where((t >= debut) & (t < fin))[0]
        for _, e in g.iterrows():
            k0 = int(np.searchsorted(t, e["entree_ms"] + LATENCE))
            if k0 >= len(t) or t[k0] - (e["entree_ms"] + LATENCE) > 2 * PAS:
                continue
            force = e["sortie_ms"] is None or (e["sortie_ms"] - e["entree_ms"]) > DETENTION_MAX
            cible = (e["entree_ms"] + DETENTION_MAX) if force else (e["sortie_ms"] + LATENCE)
            k1 = int(np.searchsorted(t, cible))
            if k1 >= len(t):
                # plus aucune bougie (barriere de l'OOS final) : sortie FORCEE a la derniere bougie connue
                k1, force = len(t) - 1, True
            elif t[k1] - cible > 2 * PAS:
                continue
            if k1 <= k0:
                continue
            duree = k1 - k0
            r = 1e4 * e["sens"] * (o[k1] / o[k0] - 1.0)
            ligne = {"vault": e["vault"], "coin": coin, "heure": int(t[k0] // G.HEURE_MS), "rendement": r,
                     "duree_h": duree * PAS / G.HEURE_MS, "sortie_forcee": bool(force)}
            cand = dans[(np.abs(dans - k0) >= 24 * 12) & (dans + duree < len(t))]
            if len(cand) >= JUMEAUX_MIN:
                contigu = (t[cand + duree] - t[cand]) == duree * PAS
                cand = cand[contigu]
                if len(cand) >= JUMEAUX_MIN:
                    ligne["jumeau"] = float(np.mean(1e4 * e["sens"] * (o[cand + duree] / o[cand] - 1.0)))
                    ligne["exces"] = r - ligne["jumeau"]
            out.append(ligne)
    return pd.DataFrame(out)


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--segment", default="execution_a", choices=("execution_a", "execution_b"))
    p.add_argument("--ecart-bps", type=float, default=6.0)
    p.add_argument("--sans-registre", action="store_true")
    p.add_argument("--ecart-mesure", default="", help="JSON {ecart_median_bps: {coin: bps}} : cout par coin MESURE (L12b)")
    a = p.parse_args(argv)
    if a.segment == "execution_b" and not a.ecart_mesure:
        print("[REFUS] la moitie B ne se lit qu'en CONFIRMATION de la regle figee L12c (--ecart-mesure obligatoire)")
        return 2
    debut, fin = G.bornes(a.segment)
    # Les CLÔTURES peuvent tomber après la fin du segment : on lit les fills jusqu'à +7 j pour les
    # apparier, mais AUCUNE ouverture hors segment n'est un signal.
    fills = G.charger("fills", a.segment, marge_apres_ms=DETENTION_MAX)
    bougies = G.charger("candles_5m", a.segment, marge_avant_ms=2 * G.JOUR_MS, marge_apres_ms=DETENTION_MAX + G.JOUR_MS)
    ev = apparier_sorties(fills)
    ev = ev[(ev["entree_ms"] >= debut) & (ev["entree_ms"] < fin)]
    df = mesurer(ev, bougies, debut=debut, fin=fin)
    cout = G.frais_aller_retour_bps() + a.ecart_bps
    hypothese = "L12_sortie_miroir"
    if a.ecart_mesure:
        import json
        mesure = json.loads(open(a.ecart_mesure, encoding="utf-8").read())["ecart_median_bps"]
        avant = len(df)
        df = df[df["coin"].isin(set(mesure))].copy()                 # coin sans écart mesuré : REFUSÉ
        df["cout"] = G.frais_aller_retour_bps() + df["coin"].map(mesure).astype(float)
        print(f"  L12b : {len(df):,} evenements sur {avant:,} ont un ecart MESURE ({df['coin'].nunique()} coins) ;"
              f" cout median {df['cout'].median():.1f} bps")
        df["net"] = df["rendement"] - df["cout"]
        cout = float(df["cout"].median())
        hypothese = "L12b_sortie_miroir_cout_mesure"
    else:
        df["net"] = df["rendement"] - cout
    jours = lambda s: (s["heure"] // 24).to_numpy()
    r = G.ic_bootstrap_par_blocs(df["rendement"].to_numpy(), jours(df))
    n = G.ic_bootstrap_par_blocs(df["net"].to_numpy(), jours(df))
    aj = df.dropna(subset=["exces"])
    ex = G.ic_bootstrap_par_blocs(aj["exces"].to_numpy(), jours(aj))
    contrib = aj.groupby("vault")["exces"].sum().sort_values(ascending=False)
    sans = aj[aj["vault"] != contrib.index[0]] if len(contrib) else aj
    ex2 = G.ic_bootstrap_par_blocs(sans["exces"].to_numpy(), jours(sans))
    print(f"  L12 sortie miroir | {a.segment} | {len(ev):,} ouvertures >= {NOTIONNEL_MIN:,.0f} USD -> {len(df):,} mesurees"
          f" | {df['vault'].nunique()} leaders | cout {cout:.1f} bps")
    print(f"  detention mediane {df['duree_h'].median():.1f} h | sorties forcees (7 j) {100 * df['sortie_forcee'].mean():.0f} %")
    print(f"  rendement brut   {r[0]:8.1f} bps [{r[1]:7.1f} ; {r[2]:7.1f}]")
    print(f"  net apres couts  {n[0]:8.1f} bps [{n[1]:7.1f} ; {n[2]:7.1f}]")
    print(f"  exces / jumeau   {ex[0]:8.1f} bps [{ex[1]:7.1f} ; {ex[2]:7.1f}]  (n {len(aj):,})")
    print(f"  sans le meilleur leader : {ex2[0]:.1f} [{ex2[1]:.1f} ; {ex2[2]:.1f}]")
    pond = float(np.average(df["net"], weights=None))
    crit = n[1] > 0 and ex[1] > 0 and ex2[1] > 0
    statut = "CANDIDAT_CONFIRMATION" if crit else "REJECTED"
    print(f"  -> {statut}")
    if not a.sans_registre:
        G.enregistrer({"hypothese": hypothese, "segment": a.segment, "statut": statut,
                       "parametres": {"latence_ms": LATENCE, "detention_max_j": 7, "ecart_bps": a.ecart_bps,
                                      "notionnel_min": NOTIONNEL_MIN},
                       "resultats": {"n": int(len(df)), "brut": [round(x, 2) for x in r], "net": [round(x, 2) for x in n],
                                     "exces": [round(x, 2) for x in ex], "exces_sans_meilleur": [round(x, 2) for x in ex2],
                                     "detention_mediane_h": round(float(df["duree_h"].median()), 2),
                                     "sorties_forcees": round(float(df["sortie_forcee"].mean()), 3), "net_moyen": round(pond, 2)}})
        print(f"  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
