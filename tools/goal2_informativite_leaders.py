r"""H15 — l'informativité d'un leader est-elle PERSISTANTE à nos horizons ? (pré-enregistrée au §19)

D'après Zhai (arXiv 2608.04373) : le classement des wallets par markout est persistant sur Hyperliquid
à 10 s. Nous copions à ~2 min ; on teste donc la persistance à 1 h, 4 h, 24 h, sur des scores causaux.

Score d'un leader à la fin d'une fenêtre de 10 jours = moyenne pondérée par le notionnel des markouts
AJUSTÉS DU MARCHÉ de ses ouvertures dont l'étiquette est connue avant la fin de la fenêtre. Évaluation
sur la fenêtre suivante : leaders du tiers supérieur contre tous les leaders classés, plus 200 tirages
placebo. LECTURE SEULE, PAPER. Une ligne au registre chaîné.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import goal2_commun as G
import goal2_etude_evenements as E
import goal2_robustesse as R

FENETRE_MS = 10 * G.JOUR_MS
LATENCE_MS = 120_000
HORIZONS = (1, 4, 24)
MIN_EVENEMENTS = 10
TIRAGES = 200


def markouts(fills: pd.DataFrame, bougies: pd.DataFrame, *, notionnel_min: float = 1000.0) -> pd.DataFrame:
    """Ouvertures agrégées, markouts bruts et ajustés du marché à chaque horizon, et instant d'étiquette."""
    ev = E.evenements(fills)
    ev = ev[ev["ouverture"] & (ev["notionnel"] >= notionnel_min)].copy()
    ev = E.rendements_futurs(ev, bougies, latence_ms=LATENCE_MS)
    heures, par_h = R.rendement_du_marche(bougies)
    instants = ev["dernier_ms"].to_numpy() + LATENCE_MS
    i0 = np.searchsorted(heures, instants, side="left")
    ok = i0 < len(heures)
    j0 = np.minimum(i0, len(heures) - 1)
    ev["entree_ms"] = np.where(ok, heures[j0], np.nan)
    for h in HORIZONS:
        marche = np.where(ok, par_h[h][j0], np.nan)
        ev[f"aj_{h}h"] = ev[f"r_{h}h"] - ev["sens_position"].to_numpy() * marche
        ev[f"connu_{h}h"] = ev["entree_ms"] + h * G.HEURE_MS
    ev["jour"] = (ev["dernier_ms"] // G.JOUR_MS).astype(np.int64)
    return ev


def scores(ev: pd.DataFrame, fin_ms: int, debut_ms: int, h: int) -> pd.Series:
    """Score causal : seuls les événements de [debut, fin[ dont l'étiquette est connue AVANT fin."""
    s = ev[(ev["dernier_ms"] >= debut_ms) & (ev[f"connu_{h}h"] < fin_ms) & np.isfinite(ev[f"aj_{h}h"])]
    g = s.groupby("vault").apply(lambda x: pd.Series({"n": len(x), "score": float(np.average(x[f"aj_{h}h"], weights=x["notionnel"]))}),
                                 include_groups=False)
    return g[g["n"] >= MIN_EVENEMENTS]["score"] if len(g) else pd.Series(dtype=float)


def evaluer(ev: pd.DataFrame, debut: int, fin: int, h: int, cout: float, *, graine: int = 20261122) -> dict:
    bornes = list(range(debut, fin, FENETRE_MS))
    lignes_top, lignes_tous, rhos, tirages = [], [], [], [[] for _ in range(TIRAGES)]
    precedent = None
    rng = np.random.default_rng(graine)
    for k in range(1, len(bornes)):
        sc = scores(ev, bornes[k], bornes[k - 1], h)
        if precedent is not None:
            commun = sc.index.intersection(precedent.index)
            if len(commun) >= 5:
                rhos.append(float(pd.Series(sc[commun]).rank().corr(pd.Series(precedent[commun]).rank())))
        precedent = sc
        if len(sc) < 6:
            continue
        top = set(sc.sort_values(ascending=False).index[: max(1, len(sc) // 3)])
        suivant = ev[(ev["dernier_ms"] >= bornes[k]) & (ev["dernier_ms"] < min(bornes[k] + FENETRE_MS, fin))
                     & ev["vault"].isin(set(sc.index)) & np.isfinite(ev[f"aj_{h}h"])]
        lignes_tous.append(suivant)
        lignes_top.append(suivant[suivant["vault"].isin(top)])
        classes = list(sc.index)
        for t in range(TIRAGES):
            choix = set(rng.choice(classes, size=len(top), replace=False))
            tirages[t].append(suivant[suivant["vault"].isin(choix)])
    if not lignes_top:
        return {"statut": "UNMEASURABLE", "motif": "trop peu de leaders classes par fenetre"}
    top, tous = pd.concat(lignes_top), pd.concat(lignes_tous)
    jt, ja = top["jour"].to_numpy(), tous["jour"].to_numpy()
    m_top = G.ic_bootstrap_par_blocs(top[f"aj_{h}h"].to_numpy(float), jt)
    m_tous = G.ic_bootstrap_par_blocs(tous[f"aj_{h}h"].to_numpy(float), ja)
    # écart top − tous, par jour (bootstrap des jours appariés)
    pj_top = top.groupby("jour")[f"aj_{h}h"].mean()
    pj_tous = tous.groupby("jour")[f"aj_{h}h"].mean()
    commun = pj_top.index.intersection(pj_tous.index)
    ecart = G.ic_bootstrap_par_blocs((pj_top[commun] - pj_tous[commun]).to_numpy(float), np.asarray(commun))
    net_top = G.ic_bootstrap_par_blocs(top[f"r_{h}h"].to_numpy(float) - cout, jt)
    plac = []
    for t in range(TIRAGES):
        d = pd.concat(tirages[t]) if tirages[t] else pd.DataFrame()
        plac.append(float(np.nanmean(d[f"aj_{h}h"])) - m_tous[0] if len(d) else np.nan)
    plac = np.asarray([x for x in plac if np.isfinite(x)])
    rang = float((plac < (m_top[0] - m_tous[0])).mean()) if len(plac) else float("nan")
    rho = (float(np.mean(rhos)), float(np.std(rhos) / max(1, np.sqrt(len(rhos)))), len(rhos)) if rhos else (float("nan"),) * 3
    return {"n_top": int(len(top)), "n_tous": int(len(tous)), "leaders_top_moyen": None,
            "top": m_top, "tous": m_tous, "ecart": ecart, "net_top": net_top,
            "placebo_rang": rang, "spearman_moyen": rho}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--segment", default="exploration", choices=("exploration", "validation"))
    p.add_argument("--confirmation", action="store_true")
    p.add_argument("--sans-registre", action="store_true")
    p.add_argument("--horizon-principal", type=int, default=4, choices=HORIZONS,
                   help="figé AVANT la mesure (H15 : 4 ; H15b, confirmation sur la validation : 24)")
    a = p.parse_args(argv)
    if a.segment == "validation" and not a.confirmation:
        print("[REFUS] la validation ne se lit qu'en confirmation d'une regle figee (--confirmation)")
        return 2
    debut, fin = G.bornes(a.segment)
    fills = G.charger("fills", a.segment)
    bougies = G.charger("candles_1h", a.segment, marge_avant_ms=4 * G.JOUR_MS, marge_apres_ms=2 * G.JOUR_MS)
    fills = fills[fills["coin"].isin(set(bougies["coin"]))]
    ev = markouts(fills, bougies)
    cout = G.frais_aller_retour_bps() + 6.0
    print(f"  H15 | {a.segment} | {len(ev):,} ouvertures >= 1 000 USD | {ev['vault'].nunique()} leaders | cout {cout:.1f} bps")
    resultats = {}
    for h in HORIZONS:
        r = evaluer(ev, debut, fin, h, cout)
        resultats[f"{h}h"] = {k: (list(map(lambda x: round(x, 3) if isinstance(x, float) else x, v)) if isinstance(v, tuple) else v)
                              for k, v in r.items()}
        if r.get("statut") == "UNMEASURABLE":
            print(f"  {h:>3} h : UNMEASURABLE — {r['motif']}")
            continue
        f = lambda t: f"{t[0]:7.1f} [{t[1]:6.1f};{t[2]:6.1f}]"
        print(f"  {h:>3} h | top {f(r['top'])} (n {r['n_top']}) | tous {f(r['tous'])} | ecart {f(r['ecart'])}"
              f" | net top {f(r['net_top'])} | placebo {100 * r['placebo_rang']:.0f} % | Spearman {r['spearman_moyen'][0]:.2f}"
              f" ± {r['spearman_moyen'][1]:.2f} ({r['spearman_moyen'][2]} paires)")
    rp = resultats[f"{a.horizon_principal}h"]
    if a.segment == "validation":       # H15b : la persistance ne se re-teste pas sur la confirmation
        ok = (rp.get("statut") != "UNMEASURABLE" and rp["ecart"][1] > 0 and rp["net_top"][1] > 0 and rp["placebo_rang"] > 0.95)
    else:
        ok = (rp.get("statut") != "UNMEASURABLE" and rp["ecart"][1] > 0 and rp["net_top"][1] > 0
              and rp["placebo_rang"] > 0.95 and rp["spearman_moyen"][0] - 1.96 * rp["spearman_moyen"][1] > 0)
    statut = ("CANDIDAT_VALIDATION" if ok and a.segment == "exploration" else ("PROMISING_HISTORIQUE" if ok else "REJECTED"))
    print(f"  -> {statut}")
    if not a.sans_registre:
        nom = "H15b_informativite_24h_confirmation" if a.segment == "validation" else "H15_persistance_informativite_leaders"
        G.enregistrer({"hypothese": nom, "segment": a.segment, "statut": statut, "horizon_principal_h": a.horizon_principal,
                       "parametres": {"fenetre_j": 10, "latence_ms": LATENCE_MS, "horizons_h": list(HORIZONS),
                                      "min_evenements": MIN_EVENEMENTS, "tirages": TIRAGES, "ecart_bps": 6.0},
                       "cout_aller_retour_bps": cout, "resultats": resultats})
        print(f"  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
