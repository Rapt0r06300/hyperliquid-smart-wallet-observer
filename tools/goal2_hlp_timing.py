r"""H23 / H24 — QUAND déposer dans HLP : un instrument sans copie de leader (pré-enregistrées au journal).

Rendement de HLP par période (pas de l'historique officiel `vaultDetails`, ~2 semaines) contre un indicateur de la
période PRÉCÉDENTE : H23 notionnel liquidé (marchés natifs, Ironflow), H24 |funding| moyen (Ironflow). Écart tiers
supérieur - tiers inférieur, IC par bootstrap des périodes, placebo par permutation, Bonferroni sur 2 tests.
LECTURE SEULE, PAPER. Une ligne au registre chaîné par test.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import goal2_commun as G

HLP = G.RACINE / "runtime" / "research_lab" / "data" / "goal2_cache" / "hlp_vault_details.json"
IRON = G.RACINE / "runtime" / "history" / "ironflow"
ALPHA = 0.025
TIRAGES = 2000


def periodes() -> pd.DataFrame:
    """(debut_ms, fin_ms, rendement) depuis l'historique allTime de HLP (PnL et valeur aux mêmes instants)."""
    rep = json.loads(HLP.read_text(encoding="utf-8"))["reponse"]
    bloc = dict(rep["portfolio"])["allTime"]
    valeur = {int(t): float(v) for t, v in bloc["accountValueHistory"]}
    pnl = [(int(t), float(v)) for t, v in bloc["pnlHistory"]]
    lignes = []
    for (t0, p0), (t1, p1) in zip(pnl, pnl[1:]):
        v0 = valeur.get(t0)
        if v0 and v0 > 0:
            lignes.append({"debut_ms": t0, "fin_ms": t1, "rendement_bps": 1e4 * (p1 - p0) / v0})
    return pd.DataFrame(lignes)


def _iron(jeu: str, colonnes: list[str], sous: str = "") -> pd.DataFrame:
    morceaux = []
    for f in sorted((IRON / jeu / "data" / sous).glob("*.parquet")):
        morceaux.append(pq.read_table(f, columns=colonnes).to_pandas())
    d = pd.concat(morceaux, ignore_index=True)
    d["t_ms"] = d["timestamp"].astype("int64") // (1000 if str(d["timestamp"].dtype).endswith("us, UTC]") else 1)
    return d


def indicateurs(p: pd.DataFrame) -> pd.DataFrame:
    liq = _iron("liquidations", ["timestamp", "market", "notional_usd"], "events")
    liq = liq[~liq["market"].str.contains(":", regex=False)]
    fun = _iron("funding", ["timestamp", "dex", "funding_rate"])
    fun = fun[fun["dex"].fillna("") == ""]
    lt, lv = liq["t_ms"].to_numpy(np.int64), liq["notional_usd"].to_numpy(float)
    ft, fv = fun["t_ms"].to_numpy(np.int64), np.abs(fun["funding_rate"].to_numpy(float))
    o = np.argsort(lt); lt, lv = lt[o], lv[o]
    o = np.argsort(ft); ft, fv = ft[o], fv[o]
    debut_liq, fin_liq = int(lt.min()), int(lt.max())
    lignes = []
    prec = None
    for _, r in p.iterrows():
        if prec is not None and prec["debut_ms"] >= debut_liq and r["debut_ms"] <= fin_liq:
            a, b = np.searchsorted(lt, prec["debut_ms"]), np.searchsorted(lt, prec["fin_ms"])
            c, d = np.searchsorted(ft, prec["debut_ms"]), np.searchsorted(ft, prec["fin_ms"])
            if d > c:
                lignes.append({**r.to_dict(), "liquide_usd_prec": float(lv[a:b].sum()), "funding_abs_prec": float(fv[c:d].mean())})
        prec = r
    return pd.DataFrame(lignes)


def tester(df: pd.DataFrame, colonne: str, *, graine: int = 20261123) -> dict:
    v, r = df[colonne].to_numpy(float), df["rendement_bps"].to_numpy(float)
    bas, haut = np.quantile(v, [1 / 3, 2 / 3])
    hi, lo = r[v >= haut], r[v <= bas]
    ecart = float(hi.mean() - lo.mean())
    rng = np.random.default_rng(graine)
    boot = []
    for _ in range(TIRAGES):
        boot.append(rng.choice(hi, len(hi)).mean() - rng.choice(lo, len(lo)).mean())
    perm = []
    for _ in range(TIRAGES):
        w = rng.permutation(v)
        perm.append(r[w >= haut].mean() - r[w <= bas].mean())
    p = float((np.asarray(perm) >= ecart).mean())
    ic = (float(np.quantile(boot, ALPHA / 2)), float(np.quantile(boot, 1 - ALPHA / 2)))
    return {"n_periodes": int(len(df)), "n_haut": int(len(hi)), "n_bas": int(len(lo)), "ecart_bps": round(ecart, 2),
            "ic_975": [round(x, 2) for x in ic], "p_permutation": round(p, 4),
            "rendement_moyen_bps": round(float(r.mean()), 2),
            "statut": "CANDIDAT_PROSPECTIF" if ic[0] > 0 and p < ALPHA else "REJECTED"}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sans-registre", action="store_true")
    a = p.parse_args(argv)
    df = indicateurs(periodes())
    print(f"  HLP | {len(df)} périodes avec indicateur de la période précédente | rendement moyen {df['rendement_bps'].mean():.1f} bps/période")
    for nom, col in (("H23_hlp_apres_liquidations", "liquide_usd_prec"), ("H24_hlp_apres_funding_extreme", "funding_abs_prec")):
        r = tester(df, col)
        print(f"  {nom:<32} haut-bas {r['ecart_bps']:+8.2f} bps [{r['ic_975'][0]:+.2f} ; {r['ic_975'][1]:+.2f}] | permutation p={r['p_permutation']}"
              f" | n {r['n_haut']}/{r['n_bas']} -> {r['statut']}")
        if not a.sans_registre:
            G.enregistrer({"hypothese": nom, "segment": "historique_hlp_complet", "statut": r["statut"],
                           "parametres": {"indicateur": col, "alpha": ALPHA, "tirages": TIRAGES, "instrument": "depot HLP (pas de copie)"},
                           "resultats": r})
    if not a.sans_registre:
        print(f"  essais enregistres (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
