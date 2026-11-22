r"""Diagnostic κ (Bai, ICAIF 2026, arXiv 2611.02616) sur NOS leaders : leurs mouvements communs sont-ils
une course au même prix public, ou des décisions indépendantes ?

Par coin, on ordonne dans le temps les fills directionnels des leaders (signe ±1). Corrélation des signes
consécutifs, séparée en paires du MÊME compte et paires de comptes DIFFÉRENTS ;
κ = C_autres / C_même. κ ≈ 1 : tous réagissent au même signal public (le copier n'apporte rien) ;
κ ≈ 0 : découpage indépendant (information propre à chacun). DIAGNOSTIC, pas une stratégie.
"""
from __future__ import annotations

import sys

import numpy as np

import goal2_commun as G


def kappa(signes: np.ndarray, comptes: np.ndarray) -> dict:
    x = signes - signes.mean()
    prod = x[1:] * x[:-1]
    meme = comptes[1:] == comptes[:-1]
    var = float((x * x).mean()) or float("nan")
    c_meme = float(prod[meme].mean()) / var if meme.any() else float("nan")
    c_autres = float(prod[~meme].mean()) / var if (~meme).any() else float("nan")
    return {"p_meme": float(meme.mean()), "c_meme": c_meme, "c_autres": c_autres,
            "kappa": c_autres / c_meme if c_meme and np.isfinite(c_meme) else float("nan"), "n": int(len(signes))}


def main() -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    f = G.charger("fills", "exploration")
    f = f[f["dir"].isin(["Open Long", "Open Short", "Close Long", "Close Short"])].sort_values(["coin", "ts_ms"], kind="stable")
    sig = np.where(f["dir"].isin(["Open Long", "Close Short"]), 1.0, -1.0)
    f = f.assign(s=sig)
    lignes = []
    for coin, g in f.groupby("coin", sort=False):
        if len(g) < 500 or g["vault"].nunique() < 3:
            continue
        k = kappa(g["s"].to_numpy(), g["vault"].to_numpy())
        lignes.append((coin, k))
    lignes.sort(key=lambda kv: -kv[1]["n"])
    print(f"  {'coin':<10}{'fills':>8}{'p_meme':>8}{'C_meme':>9}{'C_autres':>10}{'kappa':>8}")
    for coin, k in lignes[:12]:
        print(f"  {coin:<10}{k['n']:>8}{k['p_meme']:>8.2f}{k['c_meme']:>9.3f}{k['c_autres']:>10.3f}{k['kappa']:>8.2f}")
    ks = [k["kappa"] for _, k in lignes if np.isfinite(k["kappa"])]
    pm = [k["p_meme"] for _, k in lignes]
    print(f"  {len(lignes)} coins | kappa median {np.median(ks):.2f} | part de paires du meme compte mediane {np.median(pm):.2f}")
    G.enregistrer({"hypothese": "D_diagnostic_kappa_leaders", "segment": "exploration", "statut": "EXPLORATION",
                   "resultats": {"coins": len(lignes), "kappa_median": float(np.median(ks)), "p_meme_median": float(np.median(pm))}})
    print(f"  diagnostic enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
