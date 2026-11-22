r"""Etude d'evenements sur les fills des leaders : que fait le prix APRES ?

Quatre familles d'evenements, agregees par (leader, coin, heure) :

    cloture en PERTE  agressive / passive      (hypothese L2 : capitulation -> retour)
    cloture en GAIN   agressive / passive      (temoin : prise de profit)
    ouverture         agressive / passive      (hypothese L3 : derive multi-heures)

Pour chaque evenement on mesure le rendement FUTUR du coin, signe dans le sens de la POSITION
concernee (+1 si le leader etait/devient long), a 1, 4, 24 et 72 heures.

CAUSALITE. L'entree se fait a l'OUVERTURE de la premiere bougie horaire qui commence au moins
`--latence-s` secondes apres le DERNIER fill de l'evenement (defaut 120 s, au-dessus de la
mediane mesuree du retard d'observation : 98 s). Aucun prix anterieur a cet instant n'entre dans
le rendement.

INFERENCE. Les evenements d'un meme jour ne sont pas independants : l'intervalle est un
bootstrap par BLOCS de jours. Un intervalle qui contient zero = rien de mesure.

COUTS. Affiches a cote, jamais soustraits en douce : frais taker aller-retour de la source
unique du depot, plus une hypothese d'ecart DECLAREE (`--ecart-bps`), pessimiste par defaut.
Sur ces bougies on n'observe pas le carnet : le resultat est EXPLORATOIRE par construction.

LECTURE SEULE. PAPER. Chaque execution ajoute ses lignes au registre chaine des essais.
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import pandas as pd

import goal2_commun as G

HORIZONS_H = (1, 4, 24, 72)


def evenements(fills: pd.DataFrame) -> pd.DataFrame:
    """Agrege les fills en evenements (leader, coin, heure, nature)."""
    f = fills[fills["dir"].isin(["Open Long", "Open Short", "Close Long", "Close Short"])].copy()
    f["notionnel"] = f["px"] * f["sz"]
    f["ouverture"] = f["dir"].str.startswith("Open")
    f["sens_position"] = np.where(f["dir"].str.endswith("Long"), 1, -1).astype(np.int8)
    f["heure"] = f["ts_ms"] // G.HEURE_MS
    f["notionnel_agressif"] = f["notionnel"] * f["crossed"].fillna(False).astype(float)
    g = f.groupby(["vault", "coin", "heure", "ouverture", "sens_position"], sort=False).agg(
        notionnel=("notionnel", "sum"), agressif=("notionnel_agressif", "sum"),
        pnl=("closed_pnl", "sum"), frais=("fee", "sum"), dernier_ms=("ts_ms", "max"),
        n_fills=("ts_ms", "size"),
    ).reset_index()
    g["part_agressive"] = g["agressif"] / g["notionnel"].where(g["notionnel"] > 0)
    g["pnl_bps"] = 1e4 * g["pnl"] / g["notionnel"].where(g["notionnel"] > 0)
    return g


def rendements_futurs(ev: pd.DataFrame, bougies: pd.DataFrame, *, latence_ms: int) -> pd.DataFrame:
    """Ajoute `r_{H}h` (bps, signe dans le sens de la position) a chaque evenement."""
    sorties = {f"r_{h}h": np.full(len(ev), np.nan) for h in HORIZONS_H}
    entree = np.full(len(ev), np.nan)
    par_coin = {coin: (b["t_ms"].to_numpy(), b["o"].to_numpy())
                for coin, b in bougies.sort_values("t_ms").groupby("coin", sort=False)}
    for coin, idx in ev.groupby("coin", sort=False).indices.items():
        serie = par_coin.get(coin)
        if serie is None:
            continue
        t, o = serie
        instants = ev["dernier_ms"].to_numpy()[idx] + latence_ms
        i0 = np.searchsorted(t, instants, side="left")       # premiere bougie >= instant
        ok = i0 < len(t)
        # la bougie d'entree doit etre CONTIGUE : pas de trou de plus de 2 h avant l'entree
        ok &= np.where(ok, t[np.minimum(i0, len(t) - 1)] - instants <= 2 * G.HEURE_MS, False)
        prix0 = np.where(ok, o[np.minimum(i0, len(t) - 1)], np.nan)
        entree[idx] = prix0
        sens = ev["sens_position"].to_numpy()[idx]
        for h in HORIZONS_H:
            i1 = i0 + h
            ok1 = ok & (i1 < len(t))
            # la bougie de sortie doit etre exactement H heures plus tard (sinon : trou -> NaN)
            j1 = np.minimum(i1, len(t) - 1)
            ok1 &= (t[j1] - t[np.minimum(i0, len(t) - 1)]) == h * G.HEURE_MS
            r = np.where(ok1, o[j1] / prix0 - 1.0, np.nan)
            sorties[f"r_{h}h"][idx] = 1e4 * sens * r
    out = ev.copy()
    out["prix_entree"] = entree
    for nom, col in sorties.items():
        out[nom] = col
    return out


def tableau(ev: pd.DataFrame, masque: pd.Series, nom: str) -> dict:
    sous = ev[masque]
    ligne: dict = {"famille": nom, "n": int(len(sous)), "leaders": int(sous["vault"].nunique()),
                   "coins": int(sous["coin"].nunique())}
    jours = (sous["heure"] // 24).to_numpy()
    for h in HORIZONS_H:
        m, bas, haut = G.ic_bootstrap_par_blocs(sous[f"r_{h}h"].to_numpy(), jours)
        ligne[f"r_{h}h"] = {"moy_bps": round(m, 2), "ic95": [round(bas, 2), round(haut, 2)],
                            "n": int(np.isfinite(sous[f"r_{h}h"]).sum())}
    return ligne


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
    p.add_argument("--ecart-bps", type=float, default=6.0,
                   help="ecart acheteur-vendeur SUPPOSE (aller-retour), pessimiste")
    p.add_argument("--notionnel-min", type=float, default=1000.0)
    p.add_argument("--sans-registre", action="store_true")
    args = p.parse_args(argv)

    fills = G.charger("fills", args.segment)
    bougies = G.charger("candles_1h", args.segment, marge_avant_ms=G.JOUR_MS,
                        marge_apres_ms=4 * G.JOUR_MS)
    connus = set(bougies["coin"].unique())
    fills = fills[fills["coin"].isin(connus)]
    ev = evenements(fills)
    ev = ev[ev["notionnel"] >= args.notionnel_min]
    ev = rendements_futurs(ev, bougies, latence_ms=args.latence_s * 1000)

    agr = ev["part_agressive"] >= 0.5
    perte, gain = ev["pnl"] < 0, ev["pnl"] > 0
    cloture, ouverture = ~ev["ouverture"], ev["ouverture"]
    familles = [
        ("cloture en PERTE agressive", cloture & perte & agr),
        ("cloture en PERTE passive", cloture & perte & ~agr),
        ("cloture en GAIN agressive", cloture & gain & agr),
        ("cloture en GAIN passive", cloture & gain & ~agr),
        ("ouverture agressive", ouverture & agr),
        ("ouverture passive", ouverture & ~agr),
    ]
    cout = G.frais_aller_retour_bps() + args.ecart_bps
    print(f"  segment {args.segment} | {len(fills):,} fills -> {len(ev):,} evenements"
          f" (notionnel >= {args.notionnel_min:,.0f} USD) | latence {args.latence_s} s")
    print(f"  cout aller-retour retenu : {cout:.1f} bps"
          f" (frais {G.frais_aller_retour_bps():.1f} + ecart SUPPOSE {args.ecart_bps:.1f})")
    print(f"  rendement futur, en bps, dans le sens de la POSITION ; [IC95 par blocs de jours]")
    print()
    print(f"  {'famille':<30}{'n':>7}{'lead.':>6}  " + "  ".join(f"{str(h)+' h':>22}" for h in HORIZONS_H))
    lignes = []
    for nom, masque in familles:
        ligne = tableau(ev, masque, nom)
        lignes.append(ligne)
        cellules = []
        for h in HORIZONS_H:
            c = ligne[f"r_{h}h"]
            cellules.append(f"{c['moy_bps']:>7.1f} [{c['ic95'][0]:>6.1f};{c['ic95'][1]:>6.1f}]")
        print(f"  {nom:<30}{ligne['n']:>7}{ligne['leaders']:>6}  " + "  ".join(cellules))
    if not args.sans_registre:
        sha = G.enregistrer({
            "hypothese": "L2_L3_etude_d_evenements_par_nature", "segment": args.segment,
            "statut": "EXPLORATION", "parametres": {
                "latence_s": args.latence_s, "ecart_bps_suppose": args.ecart_bps,
                "notionnel_min": args.notionnel_min, "horizons_h": list(HORIZONS_H)},
            "cout_aller_retour_bps": cout, "resultats": lignes,
            "avertissement": "bougies horaires, carnet non observe : exploratoire ; univers "
                             "de leaders lents retenus en 11/2026 (biais de survie sur la direction)",
        })
        print(f"\n  essai enregistre : {sha[:16]}…  (total : {G.nombre_d_essais()})")
    print(json.dumps({"familles": len(lignes)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
