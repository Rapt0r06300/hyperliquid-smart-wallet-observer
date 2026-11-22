r"""Hypothese L1 : entrer dans la position d'un leader lent QUAND ELLE EST EN PERTE LATENTE.

MECANISME. Le suiveur arrive toujours apres le leader. Si la position du leader est sous l'eau et
qu'il la TIENT, le retard devient un avantage : on entre a MEILLEUR prix que lui, dans une
position qu'il juge encore bonne (il ne l'a pas coupee). Temoin naturel : la meme position
quand elle est en GAIN latent (on entre alors a moins bon prix que lui).

RECONSTRUCTION. Par (leader, coin), la position apres chaque fill vient de `start_position`
(position AVANT le fill, publiee par la plateforme) + sens x taille. Le prix moyen d'entree
n'est CONNU que pour un episode ouvert depuis le plat (ou un retournement) dans les donnees ;
une position heritee d'avant la fenetre n'a pas de prix d'entree -> ecartee, jamais supposee.
Un trou (le `start_position` d'un fill ne prolonge pas le fill precedent) invalide l'etat.

CAUSALITE. A l'heure t on connait : les fills jusqu'a t - latence, et la cloture de la bougie
precedente. Signal = PREMIER passage de la perte latente sous un seuil, dans l'episode.
Entree a l'ouverture de la bougie t. Sortie a horizon fixe.

BIAIS DECLARE. L'univers est celui des leaders retenus en 11/2026 : leurs positions en perte
du passe se sont, par selection, plus souvent retablies. Ce test donne donc une borne HAUTE.
S'il ne passe pas ici, il ne passera nulle part ; s'il passe, il reste a prouver en prospectif.

LECTURE SEULE, PAPER, exploratoire (bougies horaires, carnet non observe).
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import goal2_commun as G

HORIZONS_H = (4, 24, 72)
SEUILS_BPS = (-100, -300, -600, -1000, 100, 300, 600, 1000)


def etats_du_groupe(ts, px, sz, signe, sp):
    """Position, prix moyen d'entree, episode et coherence apres chaque fill d'un (leader, coin)."""
    n = len(ts)
    apres = sp + signe * sz
    entree = np.full(n, np.nan)
    connu = np.zeros(n, dtype=bool)
    episode = np.zeros(n, dtype=np.int64)
    coherent = np.ones(n, dtype=bool)          # l'etat apres i est confirme par le fill i+1
    e, k, ep = np.nan, False, 0
    for i in range(n):
        avant, ap = sp[i], apres[i]
        echelle = max(abs(avant), abs(ap), sz[i], 1e-12)
        if i > 0 and abs(avant - apres[i - 1]) > 1e-6 * max(echelle, abs(apres[i - 1])):
            coherent[i - 1] = False            # trou : l'etat herite ne vaut plus rien
            e, k = np.nan, False
            ep += 1
        if abs(ap) <= 1e-7 * echelle:
            apres[i] = 0.0
            ap = 0.0
        if abs(avant) <= 1e-7 * echelle:       # depart a plat
            ep += 1
            e, k = px[i], True
        elif avant * ap < 0:                   # retournement
            ep += 1
            e, k = px[i], True
        elif abs(ap) > abs(avant) and k:       # renfort : prix moyen pondere
            e = (abs(avant) * e + sz[i] * px[i]) / abs(ap)
        entree[i], connu[i], episode[i] = e, k, ep
    return apres, entree, connu, episode, coherent


def signaux(fills: pd.DataFrame, bougies: pd.DataFrame, *, debut: int, fin: int,
            latence_ms: int, notionnel_min: float) -> tuple[pd.DataFrame, dict]:
    # ORDRE DANS LA MILLISECONDE. Un ordre agressif produit plusieurs fills au meme instant ; les
    # trier par `tid` NE rend PAS l'ordre d'execution (mesure : 60 953 faux trous sur 112 032
    # fills, prix d'entree connu sur 13 % seulement). L'ordre vrai est celui de la chaine
    # `start_position` : croissante pour des achats, decroissante pour des ventes.
    f = fills.assign(_chaine=fills["signe"] * fills["start_position"]).sort_values(
        ["vault", "coin", "ts_ms", "_chaine"], kind="stable")
    fin_compte = f.groupby("vault")["ts_ms"].max().to_dict()
    par_coin = {coin: tuple(b[k].to_numpy() for k in ("t_ms", "o", "c"))
                for coin, b in bougies.sort_values("t_ms").groupby("coin", sort=False)}
    derives: dict = {}
    for coin, (t, o, _c) in par_coin.items():
        dans = (t >= debut) & (t < fin)
        for h in HORIZONS_H:
            if len(o) > h:
                ok = ((t[h:] - t[:-h]) == h * G.HEURE_MS) & dans[:-h]
                r = (o[h:] / o[:-h] - 1.0)[ok]
                derives[(coin, h)] = 1e4 * float(np.mean(r)) if len(r) else np.nan
    lignes: list[dict] = []
    stats = {"groupes": 0, "fills": 0, "trous": 0, "fills_prix_connu": 0}
    for (vault, coin), g in f.groupby(["vault", "coin"], sort=False):
        serie = par_coin.get(coin)
        if serie is None:
            continue
        ts = g["ts_ms"].to_numpy()
        apres, entree, connu, episode, coherent = etats_du_groupe(
            ts, g["px"].to_numpy(float), g["sz"].to_numpy(float),
            g["signe"].to_numpy(float), g["start_position"].to_numpy(float))
        stats["groupes"] += 1
        stats["fills"] += len(ts)
        stats["trous"] += int((~coherent).sum())
        stats["fills_prix_connu"] += int(connu.sum())
        t, o, c = serie
        if len(t) < 2:
            continue
        tk = t[1:]                                   # heure d'evaluation = ouverture de la bougie k
        i = np.searchsorted(ts, tk - latence_ms, side="right") - 1
        ii = np.maximum(i, 0)
        pos = apres[ii]
        ok = (i >= 0) & ((t[1:] - t[:-1]) == G.HEURE_MS) & (tk >= debut) & (tk < fin)
        ok &= (pos != 0.0) & connu[ii]
        ok &= np.where(ii < len(ts) - 1, coherent[ii], tk <= fin_compte[vault])
        if not ok.any():
            continue
        sens = np.sign(pos)
        latent = 1e4 * sens * (c[:-1] / entree[ii] - 1.0)       # cloture de la bougie precedente
        notionnel = np.abs(pos) * c[:-1]
        ok &= np.isfinite(latent) & (notionnel >= notionnel_min)
        for seuil in SEUILS_BPS:
            m = ok & ((latent <= seuil) if seuil < 0 else (latent >= seuil))
            idx = np.flatnonzero(m)
            if idx.size == 0:
                continue
            _, premiers = np.unique(episode[ii[idx]], return_index=True)   # 1er passage / episode
            for j in idx[premiers]:
                k = j + 1                                                  # bougie d'entree
                ligne = {"vault": vault, "coin": coin, "seuil": seuil, "t_ms": int(t[k]),
                         "sens": int(sens[j]), "latent_bps": float(latent[j]),
                         "notionnel": float(notionnel[j])}
                for h in HORIZONS_H:
                    if k + h < len(t) and (t[k + h] - t[k]) == h * G.HEURE_MS:
                        brut = 1e4 * (o[k + h] / o[k] - 1.0)
                        ligne[f"r_{h}h"] = sens[j] * brut
                        ligne[f"a_{h}h"] = sens[j] * (brut - derives.get((coin, h), np.nan))
                    else:
                        ligne[f"r_{h}h"] = ligne[f"a_{h}h"] = np.nan
                lignes.append(ligne)
    return pd.DataFrame(lignes), stats


def cellule(sous: pd.DataFrame, colonne: str) -> tuple[str, dict]:
    m, a, b = G.ic_bootstrap_par_blocs(sous[colonne].to_numpy(), (sous["t_ms"] // G.JOUR_MS).to_numpy())
    return f"{m:>7.1f} [{a:>7.1f};{b:>7.1f}]", {"moy_bps": round(m, 2), "ic95": [round(a, 2), round(b, 2)]}


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
    p.add_argument("--sans-registre", action="store_true")
    args = p.parse_args(argv)

    debut, fin = G.bornes(args.segment)
    # les fills ANTERIEURS au segment servent a l'ETAT (position deja ouverte) : information passee.
    fills = G.charger("fills", args.segment, marge_avant_ms=400 * G.JOUR_MS)
    bougies = G.charger("candles_1h", args.segment, marge_avant_ms=G.JOUR_MS,
                        marge_apres_ms=4 * G.JOUR_MS)
    fills = fills[fills["coin"].isin(set(bougies["coin"].unique()))]
    fills = fills[~fills["dir"].isin(["Buy", "Sell"])]
    ev, stats = signaux(fills, bougies, debut=debut, fin=fin, latence_ms=args.latence_s * 1000,
                        notionnel_min=args.notionnel_min)
    print(f"  segment {args.segment} | {stats['fills']:,} fills, {stats['groupes']:,} couples leader-coin"
          f" | trous de position : {stats['trous']:,} | fills a prix d'entree CONNU :"
          f" {100 * stats['fills_prix_connu'] / max(1, stats['fills']):.1f} %")
    print(f"  cout aller-retour : {G.frais_aller_retour_bps():.0f} bps de frais + l'ecart (non observe ici)")
    print("  bps dans le sens de la POSITION du leader ; `brut` puis `ajuste` de la derive propre du coin")
    print()
    enregistres = []
    for seuil in SEUILS_BPS:
        sous = ev[ev["seuil"] == seuil] if len(ev) else ev
        nom = f"perte latente <= {seuil}" if seuil < 0 else f"gain latent >= +{seuil}"
        print(f"  {nom:<24} n={len(sous):<5} leaders={sous['vault'].nunique() if len(sous) else 0:<3}"
              f" coins={sous['coin'].nunique() if len(sous) else 0}")
        if not len(sous):
            continue
        enreg = {"seuil_bps": seuil, "n": int(len(sous)), "leaders": int(sous["vault"].nunique())}
        for h in HORIZONS_H:
            brut, eb = cellule(sous, f"r_{h}h")
            adj, ea = cellule(sous, f"a_{h}h")
            enreg[f"{h}h"] = {"brut": eb, "ajuste": ea}
            col = f"a_{h}h"
            par_leader = sous.groupby("vault")[col].agg(["count", "mean"])
            signe = np.sign(np.nanmean(sous[col]))
            assez = par_leader[par_leader["count"] >= 3]
            meme = int((np.sign(assez["mean"]) == signe).sum())
            sans = min((float(np.nanmean(sous.loc[sous["vault"] != v, col])) for v in par_leader.index),
                       key=lambda x: signe * x) if len(par_leader) > 1 else float("nan")
            enreg[f"{h}h"].update({"meme_signe": [meme, int(len(assez))], "pire_sans_un_leader": round(sans, 2)})
            print(f"     {h:>2} h  brut {brut}   ajuste {adj}   meme signe {meme}/{len(assez)}"
                  f"   sans le leader le plus favorable {sans:>7.1f}")
        for nom_s, s in (("LONG", 1), ("SHORT", -1)):
            part = sous[sous["sens"] == s]
            if len(part):
                print(f"     72 h {nom_s:<5} n={len(part):<5} brut {cellule(part, 'r_72h')[0]}   ajuste {cellule(part, 'a_72h')[0]}")
        enregistres.append(enreg)
    if not args.sans_registre:
        G.enregistrer({"hypothese": "L1_entree_dans_une_position_en_perte_latente", "segment": args.segment,
                       "statut": "EXPLORATION", "parametres": {
                           "latence_s": args.latence_s, "notionnel_min": args.notionnel_min,
                           "seuils_bps": list(SEUILS_BPS), "horizons_h": list(HORIZONS_H)},
                       "qualite": stats, "resultats": enregistres,
                       "avertissement": "borne HAUTE : univers de leaders retenus apres coup"})
        print(f"\n  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
