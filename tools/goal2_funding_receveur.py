r"""H21 — copier le leader qui se place du côté qui REÇOIT un funding extrême (pré-enregistrée au journal).

Taux de l'heure d'entrée ≥ 90e centile des |taux| des 30 jours précédents du coin (causal). Receveur : long si
taux < 0, short si taux > 0. PnL 24 h = prix signé + funding encaissé (taux réglés du cache SAFE, recoupé avec
Ironflow) − coût. Témoin : les mêmes extrêmes où le leader PAIE. LECTURE SEULE, PAPER. Une ligne au registre.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import goal2_commun as G
import goal2_etude_evenements as E

LATENCE_MS = 120_000
TENUE_H = 24
CENTILE = 90.0
FENETRE_MS = 30 * G.JOUR_MS


def marquer(ev: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    """Ajoute taux d'entrée, seuil causal, `extreme`, `receveur` et le funding encaissé sur la tenue (bps)."""
    par_coin = {c: (g["ts_ms"].to_numpy(np.int64), g["funding"].to_numpy(float))
                for c, g in funding.sort_values("ts_ms").groupby("coin")}
    taux, seuil, encaisse = [], [], []
    for coin, entree, sens in zip(ev["coin"], ev["entree_ms"], ev["sens_position"]):
        t, r = par_coin.get(coin, (np.empty(0, np.int64), np.empty(0)))
        k = int(np.searchsorted(t, entree, side="right")) - 1             # dernier taux réglé AVANT l'entrée
        a = int(np.searchsorted(t, entree - FENETRE_MS, side="left"))
        if k < 0 or k - a < 24 * 20 or not np.isfinite(entree):
            taux.append(np.nan); seuil.append(np.nan); encaisse.append(np.nan)
            continue
        taux.append(r[k])
        seuil.append(float(np.percentile(np.abs(r[a:k + 1]), CENTILE)))
        fin = entree + TENUE_H * G.HEURE_MS
        j0, j1 = int(np.searchsorted(t, entree, side="right")), int(np.searchsorted(t, fin, side="right"))
        reglements = r[j0:j1]
        # funding INCONNU sur une partie de la tenue : on refuse la mesure, jamais un zéro favorable
        encaisse.append(-float(sens) * 1e4 * float(reglements.sum()) if len(reglements) >= TENUE_H - 1 else np.nan)
    ev = ev.assign(taux=taux, seuil=seuil, funding_bps=encaisse)
    ev["extreme"] = np.isfinite(ev["taux"]) & (ev["taux"].abs() >= ev["seuil"]) & (ev["taux"].abs() > 0)
    ev["receveur"] = ((ev["sens_position"] > 0) & (ev["taux"] < 0)) | ((ev["sens_position"] < 0) & (ev["taux"] > 0))
    return ev


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sans-registre", action="store_true")
    a = p.parse_args(argv)
    debut, fin = G.bornes("exploration")
    fills = G.charger("fills", "exploration")
    bougies = G.charger("candles_1h", "exploration", marge_avant_ms=4 * G.JOUR_MS, marge_apres_ms=2 * G.JOUR_MS)
    funding = G.charger("funding_1h", "exploration", marge_avant_ms=31 * G.JOUR_MS, marge_apres_ms=2 * G.JOUR_MS)
    fills = fills[fills["coin"].isin(set(bougies["coin"]))]
    ev = E.evenements(fills)
    ev = ev[ev["ouverture"] & (ev["notionnel"] >= 1000.0)].copy()
    ev = E.rendements_futurs(ev, bougies, latence_ms=LATENCE_MS)
    heures = np.sort(bougies["t_ms"].unique())
    i0 = np.searchsorted(heures, ev["dernier_ms"].to_numpy() + LATENCE_MS)
    ev["entree_ms"] = np.where(i0 < len(heures), heures[np.minimum(i0, len(heures) - 1)], np.nan)
    ev = marquer(ev, funding)
    cout = G.frais_aller_retour_bps() + 6.0
    ev["total"] = ev[f"r_{TENUE_H}h"] + ev["funding_bps"] - cout
    ev["jour"] = (ev["dernier_ms"] // G.JOUR_MS).astype(np.int64)
    ok = ev.dropna(subset=["total"])
    resultats = {}
    f = lambda t: f"{t[0]:7.1f} [{t[1]:6.1f};{t[2]:6.1f}]"   # noqa: E731
    print(f"  H21 | {len(ev):,} ouvertures | mesurables {len(ok):,} | extremes {int(ok['extreme'].sum())} | cout {cout:.1f} bps")
    groupes = {"receveur_extreme": ok[ok["extreme"] & ok["receveur"]], "payeur_extreme": ok[ok["extreme"] & ~ok["receveur"]],
               "hors_extreme": ok[~ok["extreme"]]}
    for nom, g in groupes.items():
        if len(g) < 2:
            resultats[nom] = {"n": int(len(g))}
            print(f"  {nom:<18} n={len(g)} : trop peu")
            continue
        j = g["jour"].to_numpy()
        r = {"n": int(len(g)), "leaders": int(g["vault"].nunique()),
             "prix": G.ic_bootstrap_par_blocs(g[f"r_{TENUE_H}h"].to_numpy(float), j),
             "funding": G.ic_bootstrap_par_blocs(g["funding_bps"].to_numpy(float), j),
             "net": G.ic_bootstrap_par_blocs(g["total"].to_numpy(float), j)}
        resultats[nom] = {k: (list(map(lambda x: round(float(x), 2), v)) if isinstance(v, tuple) else v) for k, v in r.items()}
        print(f"  {nom:<18} n={r['n']:>5} ({r['leaders']} leaders) | prix {f(r['prix'])} | funding {f(r['funding'])} | NET {f(r['net'])}")
    rec, pay = groupes["receveur_extreme"], groupes["payeur_extreme"]
    statut = "REJECTED"
    if len(rec) >= 2 and len(pay) >= 2:
        pj_r, pj_p = rec.groupby("jour")["total"].mean(), pay.groupby("jour")["total"].mean()
        commun = pj_r.index.intersection(pj_p.index)
        ecart = G.ic_bootstrap_par_blocs((pj_r[commun] - pj_p[commun]).to_numpy(float), np.asarray(commun)) if len(commun) > 1 else (np.nan,) * 3
        resultats["ecart_receveur_moins_payeur"] = [round(float(x), 2) for x in ecart]
        print(f"  ecart receveur - payeur (jours communs : {len(commun)}) : {f(ecart)}")
        if resultats["receveur_extreme"]["net"][1] > 0 and ecart[1] > 0:
            statut = "CANDIDAT_PROSPECTIF"
    print(f"  -> {statut}")
    if not a.sans_registre:
        G.enregistrer({"hypothese": "H21_cote_receveur_du_funding_extreme", "segment": "exploration", "statut": statut,
                       "parametres": {"centile": CENTILE, "fenetre_j": 30, "tenue_h": TENUE_H, "latence_ms": LATENCE_MS,
                                      "ecart_bps": 6.0}, "cout_aller_retour_bps": cout, "resultats": resultats})
        print(f"  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
