r"""Famille V : que gagne un DEPOSANT dans les vaults, et une regle de selection fait-elle mieux ?

Le depot natif n'a ni frais taker ni retard d'observation : le deposant recoit le resultat du
vault au prorata, moins 10 % de ses profits (documentation officielle). Cette etude simule ce
deposant sur les courbes publiees (matrice `goal2_vaults_matrice`, grille de 28 jours, tronquee
a la source avant le segment d'execution).

STRATEGIES (protocole et amendement V-1 au journal, ecrits avant toute mesure de rendement) :
    V0  panier egal de tous les vaults eligibles          = esperance d'un depot au hasard
    V1  panier pondere par la taille                      = rendement du dollar moyen depose
    V0h panier egal des vaults a historique complet       = reference de MEME univers pour V2-V4
    V2  qualite : anciennete +, taille +, volatilite -    quintile de tete (primaire de selection)
    V3  anti-qualite (temoin)                             quintile de queue
    V4  extremes persistants                              decile de tete du Sharpe des 6 periodes

ELIGIBILITE, jugee en DEBUT de periode : valeur du vault >= seuil (10 000 USD). Un eligible dont
le rendement est inconnu est COMPTE ; la variante pessimiste le met a -100 %.

NET du deposant : brut - 10 % de chaque periode positive (borne HAUTE des frais reels).
LECTURE SEULE, PAPER, tier LOCAL : exploratoire, jamais une preuve.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys

import numpy as np

import goal2_commun as G
import goal2_vaults_matrice as M

PERIODES_PAR_AN = 365.25 / 28.0
HISTORIQUE = 6                    # periodes d'historique exigees pour V0h, V2, V3, V4
VAULTS_MIN = 30                   # une periode a moins de 30 vaults eligibles n'est pas comptee
PART_DU_LEADER = 0.10
STRATEGIES = ("V0", "V1", "V0h", "V2", "V3", "V4")


def rangs(x: np.ndarray) -> np.ndarray:
    """Rangs moyens dans [0, 1] (egalites partagees) ; plus grand = meilleur."""
    from scipy.stats import rankdata

    return (rankdata(x, method="average") - 1.0) / max(1, len(x) - 1)


def poids_des_strategies(valeur_debut: np.ndarray, passe: np.ndarray, age_j: np.ndarray, *,
                         seuil_usd: float) -> dict[str, np.ndarray]:
    """Poids de chaque strategie sur les vaults, avec la SEULE information du debut de periode.

    `passe` : rendements des HISTORIQUE periodes precedentes (vaults x HISTORIQUE), NaN = inconnu.
    """
    n = len(valeur_debut)
    eligible = np.isfinite(valeur_debut) & (valeur_debut >= seuil_usd)
    sortie = {s: np.zeros(n) for s in STRATEGIES}
    if eligible.sum() == 0:
        return sortie
    sortie["V0"][eligible] = 1.0 / eligible.sum()
    sortie["V1"][eligible] = valeur_debut[eligible] / valeur_debut[eligible].sum()
    complet = eligible & np.isfinite(passe).all(axis=1)
    idx = np.flatnonzero(complet)
    if idx.size < 10:
        return sortie
    sortie["V0h"][idx] = 1.0 / idx.size
    ecart = passe[idx].std(axis=1, ddof=1)
    moyenne = passe[idx].mean(axis=1)
    note = (rangs(age_j[idx]) + rangs(valeur_debut[idx]) + rangs(-ecart)) / 3.0
    ordre = np.argsort(-note, kind="stable")
    q = max(1, int(np.ceil(idx.size / 5)))
    sortie["V2"][idx[ordre[:q]]] = 1.0 / q
    sortie["V3"][idx[ordre[-q:]]] = 1.0 / q
    avec_ecart = ecart > 1e-12
    if avec_ecart.sum() >= 10:
        sharpe = np.full(idx.size, -np.inf)
        sharpe[avec_ecart] = moyenne[avec_ecart] / ecart[avec_ecart]
        d = max(1, int(np.ceil(idx.size / 10)))
        tete = np.argsort(-sharpe, kind="stable")[:d]
        sortie["V4"][idx[tete]] = 1.0 / d
    return sortie


def net_du_deposant(r: np.ndarray) -> np.ndarray:
    return r - PART_DU_LEADER * np.maximum(r, 0.0)


def rendement_du_panier(poids: np.ndarray, r: np.ndarray, *, pessimiste: bool = False) -> tuple[float, float, int]:
    """(brut, net, nombre de vaults retenus sans rendement connu). Les inconnus sont soit ecartes
    (poids renormalises), soit mis a -100 % (variante pessimiste)."""
    pris = poids > 0
    if not pris.any():
        return float("nan"), float("nan"), 0
    connu = pris & np.isfinite(r)
    inconnus = int((pris & ~np.isfinite(r)).sum())
    if pessimiste:
        rr = np.where(np.isfinite(r), r, -1.0)
        return float((poids[pris] * rr[pris]).sum()), float((poids[pris] * net_du_deposant(rr[pris])).sum()), inconnus
    if not connu.any():
        return float("nan"), float("nan"), inconnus
    w = poids[connu] / poids[connu].sum()
    return float((w * r[connu]).sum()), float((w * net_du_deposant(r[connu])).sum()), inconnus


def simuler(m: dict, colonnes: np.ndarray, *, seuil_usd: float, pessimiste: bool = False) -> dict:
    ret, valeur, premier, ks = m["ret"], m["valeur"], m["premier_ms"], m["semaines"]
    series = {s: {"brut": [], "net": [], "n": [], "inconnus": []} for s in STRATEGIES}
    gardees = []
    for j in colonnes:
        if j < HISTORIQUE:
            continue
        v0 = valeur[:, j]
        if int((np.isfinite(v0) & (v0 >= seuil_usd)).sum()) < VAULTS_MIN:
            continue
        age = (int(ks[j]) * M.SEMAINE_MS - premier) / G.JOUR_MS
        poids = poids_des_strategies(v0, ret[:, j - HISTORIQUE:j], age, seuil_usd=seuil_usd)
        gardees.append(int(j))
        for s in STRATEGIES:
            b, n_, inc = rendement_du_panier(poids[s], ret[:, j], pessimiste=pessimiste)
            series[s]["brut"].append(b)
            series[s]["net"].append(n_)
            series[s]["n"].append(int((poids[s] > 0).sum()))
            series[s]["inconnus"].append(inc)
    return {"colonnes": np.array(gardees, dtype=int),
            **{s: {k: np.array(v, dtype=float) for k, v in d.items()} for s, d in series.items()}}


def ic_moyenne(x: np.ndarray, *, tirages: int = 4000, graine: int = 20261122) -> tuple[float, float, float]:
    x = x[np.isfinite(x)]
    if x.size < 3:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(graine)
    tires = x[rng.integers(0, x.size, size=(tirages, x.size))].mean(axis=1)
    bas, haut = np.quantile(tires, [0.025, 0.975])
    return float(x.mean()), float(bas), float(haut)


def repli_maximal(x: np.ndarray) -> float:
    x = np.where(np.isfinite(x), x, 0.0)
    courbe = np.cumprod(1.0 + x)
    sommet = np.maximum.accumulate(np.concatenate([[1.0], courbe]))[1:]
    return float((courbe / sommet - 1.0).min()) if courbe.size else float("nan")


def alpha_beta(x: np.ndarray, btc: np.ndarray, *, tirages: int = 4000, graine: int = 20261122) -> dict:
    ok = np.isfinite(x) & np.isfinite(btc)
    x, b = x[ok], btc[ok]
    if x.size < 8 or b.std() == 0:
        return {"n": int(x.size)}
    def ajuster(xx, bb):
        beta = np.cov(xx, bb, ddof=1)[0, 1] / bb.var(ddof=1)
        return float(xx.mean() - beta * bb.mean()), float(beta)
    a, be = ajuster(x, b)
    rng = np.random.default_rng(graine)
    tires = rng.integers(0, x.size, size=(tirages, x.size))
    alphas = np.array([ajuster(x[i], b[i])[0] for i in tires if b[i].std() > 0])
    bas, haut = np.quantile(alphas, [0.025, 0.975])
    return {"n": int(x.size), "alpha": a, "ic95": [float(bas), float(haut)], "beta": be,
            "correlation": float(np.corrcoef(x, b)[0, 1])}


def btc_aux_bornes(ks: np.ndarray) -> np.ndarray:
    """Prix de BTC a chaque borne de periode (ouverture de la bougie journaliere), NaN si absent."""
    base = G.RACINE / "runtime" / "coffre_certifie" / "local" / "shards" / "candle"
    prix: dict[int, float] = {}
    for shard in sorted(base.glob("*candles_1d*.jsonl.gz")):
        with gzip.open(shard, "rt", encoding="utf-8", errors="replace") as flux:
            for ligne in flux:
                if '"BTC"' not in ligne:
                    continue
                try:
                    o = json.loads(ligne)
                except ValueError:
                    continue
                if o.get("coin") == "BTC" and isinstance(o.get("t_ms"), int) and o.get("o"):
                    if o["t_ms"] < M.BORNE_MS:
                        prix[o["t_ms"]] = float(o["o"])
    bornes = np.concatenate([ks, [ks[-1] + 1]]) * M.SEMAINE_MS
    return np.array([prix.get(int(b), np.nan) for b in bornes])


def bps(x: float) -> str:
    return f"{1e4 * x:>8.1f}" if np.isfinite(x) else "     n/d"


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--segment", default="exploration", choices=("exploration", "validation"))
    p.add_argument("--strategie-figee", default=None, choices=STRATEGIES,
                   help="OBLIGATOIRE pour la validation : l'unique strategie retenue sur l'exploration")
    p.add_argument("--seuil-usd", type=float, default=10_000.0)
    p.add_argument("--borner", action="store_true",
                   help="ROBUSTESSE : rendements bornes a [-100 %%, +100 %%] ; un deposant ne perd pas plus "
                        "que sa mise, au-dela c'est Dietz qui se deforme sous de gros flux")
    p.add_argument("--flux-max", type=float, default=None,
                   help="ROBUSTESSE : ecarte les cellules hors cloture dont |flux / capital| depasse ce seuil")
    p.add_argument("--sans-registre", action="store_true")
    args = p.parse_args(argv)
    if args.segment == "validation" and (args.strategie_figee is None or args.sans_registre):
        print("REFUS : la validation ne se lit qu'une fois, pour UNE strategie figee d'avance"
              " (`--strategie-figee`), et toujours au registre.", file=sys.stderr)
        return 2

    m = dict(M.matrice())
    ks = m["semaines"]
    if args.flux_max is not None:            # Dietz peu fiable sous de gros flux ; les clotures sont gardees
        douteux = (np.abs(m["flux_ratio"]) > args.flux_max) & ~m["cloture"]
        m["ret"] = np.where(douteux, np.nan, m["ret"])
    if args.borner:
        m["ret"] = np.clip(m["ret"], -1.0, 1.0)
    debut_p, fin_p = ks * M.SEMAINE_MS, (ks + 1) * M.SEMAINE_MS
    borne_validation = G.SEGMENTS["validation"][0]
    if args.segment == "exploration":
        colonnes = np.flatnonzero(fin_p <= borne_validation)
    else:
        colonnes = np.flatnonzero((fin_p > borne_validation) & (fin_p <= M.BORNE_MS))
    sim = simuler(m, colonnes, seuil_usd=args.seuil_usd)
    pire = simuler(m, colonnes, seuil_usd=args.seuil_usd, pessimiste=True)
    gardees = sim["colonnes"]
    if gardees.size == 0:
        print("  aucune periode mesurable")
        return 0
    import datetime as dt

    jour = lambda ms: dt.datetime.fromtimestamp(int(ms) / 1000, dt.UTC).strftime("%d/%m/%Y")  # noqa: E731
    prix = btc_aux_bornes(ks)
    btc = prix[1:] / prix[:-1] - 1.0
    btc_g = btc[gardees]
    strategies = STRATEGIES if args.segment == "exploration" else (args.strategie_figee, "V0")
    print(f"  segment {args.segment} | {gardees.size} periodes de 28 j, du {jour(debut_p[gardees[0]])} au {jour(fin_p[gardees[-1]])}"
          f" | eligibilite : valeur >= {args.seuil_usd:,.0f} USD en debut de periode")
    print(f"  BTC sur les memes periodes : moyenne {bps(np.nanmean(btc_g))} bps/periode, connu sur {int(np.isfinite(btc_g).sum())}/{gardees.size}")
    print("  net = brut - 10 % de chaque periode positive (borne haute des frais) ; IC95 par bootstrap des periodes")
    if args.borner or args.flux_max is not None:
        print(f"  VARIANTE DE ROBUSTESSE (decidee APRES la mesure primaire) : borner={args.borner} flux_max={args.flux_max}")
    print()
    print(f"  {'':<4}{'vaults':>7}{'brut':>9}{'net':>9}   {'IC95 du net (bps/periode)':<26}{'net/an':>8}{'Sharpe':>7}{'% pos':>6}{'repli':>7}"
          f"   {'alpha vs BTC [IC95]':<28}{'beta':>6}   {'1re / 2e moitie':<18}{'pire cas':>9}")
    resultats = {}
    moitie = gardees.size // 2
    for s in strategies:
        net, brut = sim[s]["net"], sim[s]["brut"]
        moy, bas, haut = ic_moyenne(net)
        ecart = float(np.nanstd(net, ddof=1)) if np.isfinite(net).sum() > 2 else float("nan")
        sharpe = moy / ecart * np.sqrt(PERIODES_PAR_AN) if ecart and np.isfinite(ecart) and ecart > 0 else float("nan")
        ab = alpha_beta(net, btc_g)
        resultats[s] = {
            "periodes": int(np.isfinite(net).sum()), "vaults_mediane": float(np.nanmedian(sim[s]["n"])),
            "brut_moy": float(np.nanmean(brut)), "net_moy": moy, "ic95_net": [bas, haut],
            "net_annualise": moy * PERIODES_PAR_AN, "sharpe": sharpe,
            "part_positive": float(np.nanmean(net > 0)), "repli_max": repli_maximal(net),
            "alpha_beta_btc": ab, "moitie_1": float(np.nanmean(net[:moitie])), "moitie_2": float(np.nanmean(net[moitie:])),
            "inconnus_total": int(np.nansum(sim[s]["inconnus"])), "pire_cas_net_moy": float(np.nanmean(pire[s]["net"])),
            "autocorrelation_1": float(np.corrcoef(net[:-1], net[1:])[0, 1]) if np.isfinite(net).all() and net.size > 3 else float("nan"),
        }
        r = resultats[s]
        alpha = (f"{bps(ab['alpha'])} [{1e4 * ab['ic95'][0]:>7.1f};{1e4 * ab['ic95'][1]:>7.1f}]" if "alpha" in ab else "n/d")
        beta = f"{ab['beta']:>6.2f}" if "beta" in ab else "   n/d"
        print(f"  {s:<4}{r['vaults_mediane']:>7.0f}{bps(r['brut_moy'])}{bps(moy)}   [{1e4 * bas:>8.1f};{1e4 * haut:>8.1f}]      "
              f"{100 * r['net_annualise']:>7.1f}%{sharpe:>7.2f}{100 * r['part_positive']:>5.0f}%{100 * r['repli_max']:>6.0f}%"
              f"   {alpha:<28}{beta}   {bps(r['moitie_1'])} /{bps(r['moitie_2'])}  {bps(r['pire_cas_net_moy'])}")
    exces = {}
    if args.segment == "exploration":
        print()
        print("  EXCES apparie (net), en bps par periode [IC95] :")
        for s, ref in (("V1", "V0"), ("V2", "V0"), ("V2", "V0h"), ("V3", "V0h"), ("V4", "V0"), ("V4", "V0h"), ("V2", "V3")):
            d = sim[s]["net"] - sim[ref]["net"]
            moy, bas, haut = ic_moyenne(d)
            exces[f"{s}-{ref}"] = {"moy": moy, "ic95": [bas, haut], "n": int(np.isfinite(d).sum())}
            print(f"     {s:<3} - {ref:<3} : {bps(moy)} [{1e4 * bas:>8.1f};{1e4 * haut:>8.1f}]  (n={int(np.isfinite(d).sum())})")
        inc = resultats["V0"]["inconnus_total"]
        total = int(np.nansum(sim["V0"]["n"]))
        print(f"\n  eligibles sans rendement connu (V0) : {inc:,} sur {total:,} vault-periodes ({100 * inc / max(1, total):.1f} %)"
              f" ; autocorrelation d'ordre 1 de V0 : {resultats['V0']['autocorrelation_1']:.2f}")
    if not args.sans_registre:
        G.enregistrer({"hypothese": "V_allocation_par_depot_dans_les_vaults", "segment": args.segment,
                       "statut": "VALIDATION" if args.segment == "validation" else "EXPLORATION",
                       "parametres": {"seuil_usd": args.seuil_usd, "historique_periodes": HISTORIQUE,
                                      "vaults_min": VAULTS_MIN, "part_du_leader": PART_DU_LEADER,
                                      "grille_j": 28, "strategie_figee": args.strategie_figee,
                                      "borner": bool(args.borner), "flux_max": args.flux_max},
                       "periodes": [int(x) for x in ks[gardees]], "resultats": resultats, "exces": exces,
                       "avertissement": "tier LOCAL, courbes relues apres coup ; survie residuelle (vaults ouverts vides absents)"})
        print(f"\n  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
