r"""H17 — le leader qui ABSORBE une vague de liquidations (pré-enregistrée au §22 du journal).

Vague = heure où le notionnel liquidé d'un coin natif dépasse 1 M USD ET 5 fois sa médiane des 30 jours
précédents (causal). L'absorbeur prend le côté opposé aux positions liquidées. Événement = ouverture d'un
leader dans le sens de l'absorbeur, dans l'heure de la vague ou la suivante ; entrée à la première bougie
1 h après le dernier fill + 120 s ET après la fin de la vague. Jumeau sans leader (même coin, même sens,
même mouvement des 72 h). Liquidations : Ironflow (`runtime/history/ironflow/liquidations`, recoupé).
LECTURE SEULE, PAPER. Une ligne au registre chaîné.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import goal2_commun as G
import goal2_etude_evenements as E
import goal2_placebo_position_en_perte as P

LATENCE_MS = 120_000
HORIZONS = (4, 24)
SEUIL_USD = 1_000_000.0
MULTIPLE = 5.0
FENETRE_H = 30 * 24
DOSSIER_LIQ = G.RACINE / "runtime" / "history" / "ironflow" / "liquidations" / "data" / "events"


def liquidations_horaires(debut: int, fin: int) -> pd.DataFrame:
    """(coin, heure_ms, long_usd, short_usd) des coins NATIFS, de debut − 30 j à fin."""
    mois = pd.period_range(pd.Timestamp(debut - FENETRE_H * G.HEURE_MS, unit="ms"), pd.Timestamp(fin, unit="ms"), freq="M")
    morceaux = []
    for m in mois:
        f = DOSSIER_LIQ / f"{m.strftime('%Y-%m')}.parquet"
        if not f.exists():
            raise FileNotFoundError(f"liquidations absentes pour {m} : la mesure serait biaisée, refus")
        t = pq.read_table(f, columns=["timestamp", "market", "position_side", "notional_usd"]).to_pandas()
        morceaux.append(t[~t["market"].str.contains(":", regex=False) & t["market"].str.endswith("-PERP")])
    d = pd.concat(morceaux, ignore_index=True)
    d["coin"] = d["market"].str[:-5]
    d["heure_ms"] = (d["timestamp"].astype("int64") // G.HEURE_MS) * G.HEURE_MS
    p = d.pivot_table(index=["coin", "heure_ms"], columns="position_side", values="notional_usd", aggfunc="sum", fill_value=0.0)
    p = p.rename(columns={"long": "long_usd", "short": "short_usd"}).reset_index()
    for c in ("long_usd", "short_usd"):
        if c not in p:
            p[c] = 0.0
    return p


def vagues(liq: pd.DataFrame, debut: int, fin: int) -> pd.DataFrame:
    """Heures de vague, avec le sens de l'absorbeur (+1 achète les ventes forcées des longs liquidés)."""
    sorties = []
    grille = np.arange((debut - FENETRE_H * G.HEURE_MS) // G.HEURE_MS * G.HEURE_MS, fin, G.HEURE_MS)
    for coin, g in liq.groupby("coin", sort=False):
        s = g.set_index("heure_ms")[["long_usd", "short_usd"]].reindex(grille, fill_value=0.0)
        total = s["long_usd"] + s["short_usd"]
        mediane = total.rolling(FENETRE_H, min_periods=FENETRE_H).median().shift(1)   # causal : heures PASSÉES seules
        ok = (total >= SEUIL_USD) & (total >= MULTIPLE * mediane) & (s.index >= debut) & (s.index < fin)
        for h in s.index[ok.to_numpy()]:
            sens = 1 if s.at[h, "long_usd"] >= s.at[h, "short_usd"] else -1
            sorties.append({"coin": coin, "heure_ms": int(h), "sens_absorbeur": sens, "liquide_usd": float(total.at[h])})
    return pd.DataFrame(sorties)


def evenements(fills: pd.DataFrame, vg: pd.DataFrame, *, notionnel_min: float = 1000.0) -> pd.DataFrame:
    ev = E.evenements(fills)
    ev = ev[ev["ouverture"] & (ev["notionnel"] >= notionnel_min)].copy()
    par_coin = {c: g.sort_values("heure_ms") for c, g in vg.groupby("coin")}
    dans_vague = np.zeros(len(ev), dtype=bool)
    entree = ev["dernier_ms"].to_numpy(np.int64) + LATENCE_MS
    for i, (coin, t, sens) in enumerate(zip(ev["coin"], ev["dernier_ms"], ev["sens_position"])):
        g = par_coin.get(coin)
        if g is None:
            continue
        h = g["heure_ms"].to_numpy()
        k = np.searchsorted(h, t - 2 * G.HEURE_MS, side="right")
        for j in range(k, len(h)):
            if h[j] > t:
                break
            if h[j] <= t < h[j] + 2 * G.HEURE_MS and int(g["sens_absorbeur"].iloc[j]) == int(sens):
                dans_vague[i] = True
                entree[i] = max(entree[i], int(h[j]) + G.HEURE_MS)       # la vague est connue en entier
                break
    ev["absorbe"] = dans_vague
    ev["entree_ms"] = entree
    return ev


def mesurer(ev: pd.DataFrame, bougies: pd.DataFrame, *, debut: int, fin: int) -> pd.DataFrame:
    t_par = {c: g["t_ms"].to_numpy(np.int64) for c, g in bougies.sort_values("t_ms").groupby("coin")}
    lignes = []
    for _, e in ev.iterrows():
        t = t_par.get(e["coin"])
        if t is None:
            continue
        k = int(np.searchsorted(t, e["entree_ms"]))
        if k >= len(t) or t[k] - e["entree_ms"] > 2 * G.HEURE_MS:
            continue
        lignes.append({"vault": e["vault"], "coin": e["coin"], "seuil": 0, "t_ms": int(t[k]),
                       "sens": int(e["sens_position"]), "absorbe": bool(e["absorbe"])})
    df = pd.DataFrame(lignes)
    if df.empty:
        return df
    j = P.jumeler(df, bougies, debut=debut, fin=fin, passe_h=72, horizons=HORIZONS)
    j["absorbe"] = df["absorbe"].to_numpy()
    j["heure"] = (j["t_ms"] // G.HEURE_MS).astype(np.int64)
    return j


def bilan(df: pd.DataFrame, h: int, cout: float) -> dict:
    if df.empty:
        return {"n": 0, "statut": "UNMEASURABLE"}
    jours = (df["heure"] // 24).to_numpy()
    brut = G.ic_bootstrap_par_blocs(df[f"ev_{h}h"].to_numpy(float), jours)
    net = G.ic_bootstrap_par_blocs(df[f"ev_{h}h"].to_numpy(float) - cout, jours)
    ok = df.dropna(subset=[f"ex_{h}h"])
    ex = G.ic_bootstrap_par_blocs(ok[f"ex_{h}h"].to_numpy(float), (ok["heure"] // 24).to_numpy()) if len(ok) else (np.nan,) * 3
    contrib = ok.groupby("vault")[f"ex_{h}h"].sum().sort_values(ascending=False)
    sans = ok[ok["vault"] != contrib.index[0]] if len(contrib) else ok
    ex2 = (G.ic_bootstrap_par_blocs(sans[f"ex_{h}h"].to_numpy(float), (sans["heure"] // 24).to_numpy())
           if len(sans) > 1 else (np.nan,) * 3)
    return {"n": int(len(df)), "leaders": int(df["vault"].nunique()), "jours": int(len(set(jours))),
            "brut": brut, "net": net, "exces": ex, "exces_sans_meilleur": ex2}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--segment", default="exploration", choices=("exploration",))
    p.add_argument("--sans-registre", action="store_true")
    a = p.parse_args(argv)
    debut, fin = G.bornes(a.segment)
    vg = vagues(liquidations_horaires(debut, fin), debut, fin)
    fills = G.charger("fills", a.segment)
    bougies = G.charger("candles_1h", a.segment, marge_avant_ms=4 * G.JOUR_MS, marge_apres_ms=2 * G.JOUR_MS)
    fills = fills[fills["coin"].isin(set(bougies["coin"]))]
    ev = evenements(fills, vg)
    df = mesurer(ev, bougies, debut=debut, fin=fin)
    cout = G.frais_aller_retour_bps() + 6.0
    print(f"  H17 | {a.segment} | {len(vg):,} vagues sur {vg['coin'].nunique() if len(vg) else 0} coins"
          f" | ouvertures {len(ev):,} dont absorbantes {int(ev['absorbe'].sum()):,} | mesurees {len(df):,} | cout {cout:.1f} bps")
    resultats = {}
    f = lambda t: f"{t[0]:7.1f} [{t[1]:6.1f};{t[2]:6.1f}]"   # noqa: E731
    for nom, masque in (("absorbe", df["absorbe"]), ("temoin_hors_vague", ~df["absorbe"])) if len(df) else ():
        for h in HORIZONS:
            b = bilan(df[masque], h, cout)
            resultats[f"{nom}_{h}h"] = {k: (list(map(lambda x: round(float(x), 2), v)) if isinstance(v, tuple) else v)
                                         for k, v in b.items()}
            if b["n"]:
                print(f"  {nom:<18}{h:>3} h | n {b['n']:>5} ({b['leaders']} leaders, {b['jours']} j) | brut {f(b['brut'])}"
                      f" | net {f(b['net'])} | exces {f(b['exces'])} | sans meilleur [{b['exces_sans_meilleur'][1]:6.1f};"
                      f"{b['exces_sans_meilleur'][2]:6.1f}]")
    # Diagnostic sans leader : le marché après la vague, dans le sens de l'absorbeur (pas une stratégie)
    diag = []
    t_par = {c: g.sort_values("t_ms") for c, g in bougies.groupby("coin")}
    for _, v in vg.iterrows():
        b = t_par.get(v["coin"])
        if b is None:
            continue
        t = b["t_ms"].to_numpy(np.int64)
        k = int(np.searchsorted(t, v["heure_ms"] + G.HEURE_MS))
        if k + 24 < len(t) and t[k + 24] - t[k] == 24 * G.HEURE_MS:
            o = b["o"].to_numpy(float)
            diag.append((int(v["heure_ms"] // G.JOUR_MS), 1e4 * v["sens_absorbeur"] * (o[k + 24] / o[k] - 1.0)))
    if diag:
        d = G.ic_bootstrap_par_blocs(np.array([x[1] for x in diag]), np.array([x[0] for x in diag]))
        resultats["diagnostic_marche_apres_vague_24h"] = {"n": len(diag), "brut": [round(float(x), 2) for x in d]}
        print(f"  diagnostic marche apres vague (sans leader) 24 h | n {len(diag)} | {f(d)} bps")
    r = resultats.get("absorbe_24h", {})
    critere = bool(r.get("n")) and r["exces"][1] > 0 and r["net"][1] > 0 and r["exces_sans_meilleur"][1] > 0
    statut = "CANDIDAT_PROSPECTIF" if critere else ("UNMEASURABLE" if not r.get("n") else "REJECTED")
    print(f"  -> {statut}")
    if not a.sans_registre:
        G.enregistrer({"hypothese": "H17_absorption_des_liquidations", "segment": a.segment, "statut": statut,
                       "parametres": {"seuil_usd": SEUIL_USD, "multiple": MULTIPLE, "fenetre_h": FENETRE_H,
                                      "latence_ms": LATENCE_MS, "horizons_h": list(HORIZONS), "ecart_bps": 6.0,
                                      "source_liquidations": "Ironflow events (CC BY 4.0), recoupe"},
                       "cout_aller_retour_bps": cout, "resultats": resultats})
        print(f"  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
