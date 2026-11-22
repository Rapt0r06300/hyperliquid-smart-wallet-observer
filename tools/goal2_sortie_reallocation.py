r"""H14 — la fermeture de RÉALLOCATION (pré-enregistrée au §18 du journal).

Source : von Beschwitz, Lunghi & Schmidt (FEDS 2021-022) — des gérants habiles ferment trop tôt pour
réallouer leur capital ; le prix continue ensuite dans le sens de la position fermée.

Un leader qui ferme une position ET en ouvre une sur un AUTRE coin dans [−1 h, +1 h] réalloue. Le
suiveur reprend la position fermée. Entrée à la première bougie 1 h ≥ max(fermeture, ouverture) + 120 s :
la classification n'utilise rien d'inconnu à l'entrée. Témoin interne : fermetures sans réallocation.
Jumeau : même coin, même sens, même mouvement passé (`goal2_placebo_position_en_perte.jumeler`).
LECTURE SEULE, PAPER. Une ligne au registre chaîné.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import goal2_commun as G
import goal2_etude_evenements as E
import goal2_placebo_position_en_perte as P

LATENCE_MS = 120_000
FENETRE_MS = G.HEURE_MS
HORIZONS = (24, 72)


def classer(fills: pd.DataFrame, *, notionnel_min: float = 1000.0) -> pd.DataFrame:
    """Fermetures agrégées, avec `reallocation` et l'instant d'entrée causal."""
    ev = E.evenements(fills)
    ev = ev[ev["notionnel"] >= notionnel_min]
    ouv = ev[ev["ouverture"]][["vault", "coin", "dernier_ms"]]
    fer = ev[~ev["ouverture"]].copy()
    par_vault = {v: (g["dernier_ms"].to_numpy(np.int64), g["coin"].to_numpy())
                 for v, g in ouv.sort_values("dernier_ms").groupby("vault")}
    realloc = np.zeros(len(fer), dtype=bool)
    entree = fer["dernier_ms"].to_numpy(np.int64).copy()
    for i, (v, coin, t) in enumerate(zip(fer["vault"], fer["coin"], fer["dernier_ms"])):
        ts, coins = par_vault.get(v, (np.empty(0, np.int64), np.empty(0)))
        a, b = np.searchsorted(ts, t - FENETRE_MS), np.searchsorted(ts, t + FENETRE_MS, side="right")
        autres = [k for k in range(a, b) if coins[k] != coin]
        if autres:
            realloc[i] = True
            entree[i] = max(int(t), int(ts[autres[0]]))       # on attend d'avoir VU l'ouverture
    fer["reallocation"] = realloc
    fer["entree_ms"] = entree + LATENCE_MS
    return fer


def mesurer(fer: pd.DataFrame, bougies: pd.DataFrame, *, debut: int, fin: int) -> pd.DataFrame:
    t_par = {c: g["t_ms"].to_numpy(np.int64) for c, g in bougies.sort_values("t_ms").groupby("coin")}
    lignes = []
    for _, e in fer.iterrows():
        t = t_par.get(e["coin"])
        if t is None:
            continue
        k = int(np.searchsorted(t, e["entree_ms"]))
        if k >= len(t) or t[k] - e["entree_ms"] > 2 * G.HEURE_MS:
            continue
        lignes.append({"vault": e["vault"], "coin": e["coin"], "seuil": 0, "t_ms": int(t[k]),
                       "sens": int(e["sens_position"]), "reallocation": bool(e["reallocation"])})
    ev = pd.DataFrame(lignes)
    if ev.empty:
        return ev
    j = P.jumeler(ev, bougies, debut=debut, fin=fin, passe_h=72, horizons=HORIZONS)
    j["reallocation"] = ev["reallocation"].to_numpy()
    j["heure"] = (j["t_ms"] // G.HEURE_MS).astype(np.int64)
    return j


def bilan(df: pd.DataFrame, h: int, cout: float) -> dict:
    jours = (df["heure"] // 24).to_numpy()
    ev = G.ic_bootstrap_par_blocs(df[f"ev_{h}h"].to_numpy(float), jours)
    net = G.ic_bootstrap_par_blocs(df[f"ev_{h}h"].to_numpy(float) - cout, jours)
    ok = df.dropna(subset=[f"ex_{h}h"])
    ex = G.ic_bootstrap_par_blocs(ok[f"ex_{h}h"].to_numpy(float), (ok["heure"] // 24).to_numpy())
    contrib = ok.groupby("vault")[f"ex_{h}h"].sum().sort_values(ascending=False)
    sans = ok[ok["vault"] != contrib.index[0]] if len(contrib) else ok
    ex2 = G.ic_bootstrap_par_blocs(sans[f"ex_{h}h"].to_numpy(float), (sans["heure"] // 24).to_numpy())
    return {"n": int(len(df)), "leaders": int(df["vault"].nunique()), "brut": ev, "net": net, "exces": ex,
            "exces_sans_meilleur": ex2}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--segment", default="exploration", choices=("exploration", "validation"))
    p.add_argument("--confirmation", action="store_true", help="obligatoire pour lire la validation (une fois)")
    p.add_argument("--sans-registre", action="store_true")
    a = p.parse_args(argv)
    if a.segment == "validation" and not a.confirmation:
        print("[REFUS] la validation ne se lit qu'en confirmation d'une regle figee (--confirmation)")
        return 2
    debut, fin = G.bornes(a.segment)
    fills = G.charger("fills", a.segment, marge_apres_ms=FENETRE_MS)
    fills = fills[fills["ts_ms"] < fin + FENETRE_MS]
    bougies = G.charger("candles_1h", a.segment, marge_avant_ms=4 * G.JOUR_MS, marge_apres_ms=4 * G.JOUR_MS)
    fills = fills[fills["coin"].isin(set(bougies["coin"]))]
    fer = classer(fills)
    fer = fer[(fer["dernier_ms"] >= debut) & (fer["dernier_ms"] < fin)]
    df = mesurer(fer, bougies, debut=debut, fin=fin)
    cout = G.frais_aller_retour_bps() + 6.0
    print(f"  H14 | {a.segment} | fermetures {len(fer):,} dont reallocation {int(fer['reallocation'].sum()):,}"
          f" | mesurees {len(df):,} | cout {cout:.1f} bps")
    resultats = {}
    for nom, masque in (("reallocation", df["reallocation"]), ("temoin_sans_reallocation", ~df["reallocation"])):
        for h in HORIZONS:
            b = bilan(df[masque], h, cout)
            resultats[f"{nom}_{h}h"] = {k: (list(map(lambda x: round(x, 2), v)) if isinstance(v, tuple) else v)
                                         for k, v in b.items()}
            print(f"  {nom:<26}{h:>3} h | n {b['n']:>6} | brut {b['brut'][0]:7.1f} [{b['brut'][1]:6.1f};{b['brut'][2]:6.1f}]"
                  f" | net {b['net'][0]:7.1f} [{b['net'][1]:6.1f};{b['net'][2]:6.1f}]"
                  f" | exces {b['exces'][0]:6.1f} [{b['exces'][1]:6.1f};{b['exces'][2]:6.1f}]"
                  f" | sans meilleur [{b['exces_sans_meilleur'][1]:6.1f};{b['exces_sans_meilleur'][2]:6.1f}]")
    r = resultats["reallocation_24h"]
    critere = r["exces"][1] > 0 and r["net"][1] > 0 and r["exces_sans_meilleur"][1] > 0
    statut = ("CANDIDAT_VALIDATION" if critere and a.segment == "exploration"
              else ("PROMISING_HISTORIQUE" if critere else "REJECTED"))
    print(f"  -> {statut}")
    if not a.sans_registre:
        G.enregistrer({"hypothese": "H14_fermeture_de_reallocation", "segment": a.segment, "statut": statut,
                       "parametres": {"fenetre_ms": FENETRE_MS, "latence_ms": LATENCE_MS, "horizons_h": list(HORIZONS),
                                      "notionnel_min": 1000.0, "ecart_bps": 6.0},
                       "cout_aller_retour_bps": cout, "resultats": resultats})
        print(f"  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
