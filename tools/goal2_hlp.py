r"""V5 : que rapporte un depot dans HLP, le vault du protocole ? (pre-enregistre au journal, section 10)

HLP est EXCLU du coffre (`VAULTS_EXCLUS`) : sa courbe n'a jamais ete collectee. Ce script la lit
UNE fois (`--lire`) sur l'API officielle, en lecture seule -- la requete ne contient que l'adresse
publique du vault -- et range la reponse brute, horodatee, dans le cache de recherche.

⚠ Cette donnee n'est PAS dans le coffre certifie : tout ce qui en sort est EXPLORATOIRE.

MESURE : meme grille de 28 jours, meme Dietz et meme troncature au verrou que la famille V
(`goal2_vaults_matrice.construire`). HLP ne preleve aucune part de profit : net = brut.
Conditions officielles : blocage de 4 jours apres depot.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

import numpy as np

import goal2_commun as G
import goal2_depot_vaults as D
import goal2_vaults_matrice as M

HLP = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"      # la meme adresse que `collecter_vaults.VAULTS_EXCLUS`
URL_INFO = "https://api.hyperliquid.xyz/info"
BRUT = G.CACHE / "hlp_vault_details.json"
#: PROSPECTIF. La regle « deposer dans HLP et tenir » est figee le 22/11/2026. Ne compte comme preuve
#: prospective qu'une periode qui COMMENCE apres ce gel : la premiere borne de la grille de 28 jours
#: posterieure au 22/11/2026 (le 17/12/2026). Minimum de periodes avant tout verdict : 6.
GEL_MS = G._ms(2026, 11, 22)
PROSPECTIF_K = -(-GEL_MS // M.SEMAINE_MS)          # premiere borne >= gel
PROSPECTIF_MIN = 6
#: Depot PAPIER de 100 USD dans HLP : un registre chaine, alimente a chaque lecture. Rien n'y est
#: jamais recalcule sur le passe : une marque ne s'appuie que sur les points POSTERIEURS a la precedente.
PAPIER = G.REGISTRE.with_name("HLP_PAPIER.ndjson")
CAPITAL_PAPIER_USD = 100.0


def lire() -> dict:
    charge = json.dumps({"type": "vaultDetails", "vaultAddress": HLP}).encode("utf-8")
    requete = urllib.request.Request(URL_INFO, data=charge, method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(requete, timeout=30) as reponse:      # noqa: S310 (URL constante, lecture seule)
        corps = json.loads(reponse.read().decode("utf-8"))
    BRUT.parent.mkdir(parents=True, exist_ok=True)
    BRUT.write_text(json.dumps({"lu_ms": int(time.time() * 1000), "source": URL_INFO, "vault": HLP,
                                "reponse": corps}, ensure_ascii=False), encoding="utf-8")
    return corps


def courbe(reponse: dict) -> list[tuple[int, float | None, float | None]]:
    from hl_observer.collection.vault_portfolio_history import extraire_fenetres, fusionner_points

    lignes = [{"vault": HLP, "fenetre": nom, "points": bloc["points"], "pnl_base": bloc.get("pnl_base")}
              for nom, bloc in extraire_fenetres(reponse).items()]
    return fusionner_points(lignes).get(HLP, [])


def marquer(points: list, precedent: dict | None) -> list[dict]:
    """Les lignes a AJOUTER au registre papier, a partir des seuls points posterieurs au precedent.

    Sans precedent : le DEPOT, au dernier point connu (on entre au prix du jour, jamais dans le passe).
    Sinon : une MARQUE par point nouveau, chainee par Dietz (un depot d'autrui n'est pas un gain).
    Un point sans valeur ou sans PnL est ignore ; aucun point nouveau -> aucune ligne.
    """
    connus = sorted((int(p[0]), float(p[1]), float(p[2])) for p in points if p[1] is not None and p[2] is not None)
    if not connus:
        return []
    if precedent is None:
        ts, valeur, pnl = connus[-1]
        return [{"type": "DEPOT", "ts_ms": ts, "valeur_vault": valeur, "pnl_vault": pnl,
                 "capital_usd": CAPITAL_PAPIER_USD, "blocage_jours": 4, "paper": True}]
    lignes, q = [], (int(precedent["ts_ms"]), float(precedent["valeur_vault"]), float(precedent["pnl_vault"]))
    capital = float(precedent["capital_usd"])
    for ts, valeur, pnl in connus:
        if ts <= q[0]:
            continue
        gain = pnl - q[2]
        moyen = q[1] + 0.5 * ((valeur - q[1]) - gain)
        if moyen <= 0:                       # capital moyen non defini : on REFUSE de marquer
            break
        capital *= max(0.0, 1.0 + gain / moyen)
        q = (ts, valeur, pnl)
        lignes.append({"type": "MARQUE", "ts_ms": ts, "valeur_vault": valeur, "pnl_vault": pnl,
                       "capital_usd": round(capital, 6), "paper": True})
    return lignes


def papier(c: list) -> int:
    import datetime as dt
    from etude_copiabilite import append_ledger

    precedent = None
    if PAPIER.is_file():
        existantes = [json.loads(x) for x in PAPIER.read_text(encoding="utf-8").splitlines() if x.strip()]
        precedent = existantes[-1] if existantes else None
    nouvelles = marquer(c, precedent)
    for ligne in nouvelles:
        append_ledger(PAPIER, {"schema": "alina.goal2.hlp_papier.v1", **ligne})
    jour = lambda ms: dt.datetime.fromtimestamp(int(ms) / 1000, dt.UTC).strftime("%d/%m/%Y %H:%M")  # noqa: E731
    lignes = [json.loads(x) for x in PAPIER.read_text(encoding="utf-8").splitlines() if x.strip()] if PAPIER.is_file() else []
    if not lignes:
        print("  HLP PAPIER : aucune donnee -> rien d'ecrit")
        return 3
    depot, derniere = lignes[0], lignes[-1]
    jours = (derniere["ts_ms"] - depot["ts_ms"]) / G.JOUR_MS
    print(f"  HLP PAPIER | depot de {depot['capital_usd']:.2f} USD le {jour(depot['ts_ms'])} UTC | {len(nouvelles)} ligne(s) ajoutee(s)")
    print(f"  derniere marque : {jour(derniere['ts_ms'])} UTC -> {derniere['capital_usd']:.4f} USD"
          f"  ({derniere['capital_usd'] - depot['capital_usd']:+.4f} USD en {jours:.1f} jours)")
    return 0


def prospectif(c: list, *, enregistrer: bool = True) -> int:
    """Les SEULES periodes commencees apres le gel de la regle. Rien d'anterieur n'est lu."""
    import datetime as dt

    futur = [p for p in c if int(p[0]) >= PROSPECTIF_K * M.SEMAINE_MS - M.PERIME_MS]
    jour = lambda ms: dt.datetime.fromtimestamp(int(ms) / 1000, dt.UTC).strftime("%d/%m/%Y")  # noqa: E731
    x = np.array([])
    if len(futur) >= 2:
        m = M.construire({HLP: futur}, borne_ms=10**15)
        garde = np.isfinite(m["ret"][0]) & (m["semaines"] >= PROSPECTIF_K)
        x = np.clip(m["ret"][0][garde], -1.0, 1.0)
    statut = "MORE_DATA"
    print(f"  HLP PROSPECTIF | regle figee le {jour(GEL_MS)} ; premiere periode comptee : {jour(PROSPECTIF_K * M.SEMAINE_MS)}"
          f" | periodes closes : {x.size} (minimum {PROSPECTIF_MIN})")
    if x.size >= PROSPECTIF_MIN:
        moy, bas, haut = D.ic_moyenne(x)
        statut = "PROVEN" if bas > 0 else ("REJECTED" if haut < 0 else "MORE_DATA")
        print(f"  rendement par periode : {1e4 * moy:.1f} bps [{1e4 * bas:.1f} ; {1e4 * haut:.1f}] | positives {100 * np.mean(x > 0):.0f} %")
    print(f"  STATUT PROSPECTIF : {statut}")
    if enregistrer:
        G.enregistrer({"hypothese": "V5_depot_dans_HLP", "segment": "prospectif", "statut": statut,
                       "periodes": int(x.size), "rendements": [float(r) for r in x]})
    return 0


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lire", action="store_true", help="une lecture de l'API officielle (sinon : cache)")
    p.add_argument("--segment", default="exploration", choices=("exploration", "validation", "prospectif", "papier"))
    p.add_argument("--sans-registre", action="store_true")
    args = p.parse_args(argv)
    if args.segment == "validation" and args.sans_registre:
        print("REFUS : une lecture de la validation est toujours enregistree.", file=sys.stderr)
        return 2
    if args.lire:
        reponse = lire()
    elif BRUT.is_file():
        reponse = json.loads(BRUT.read_text(encoding="utf-8"))["reponse"]
    else:
        print("REFUS : aucune courbe HLP en cache ; lancer une fois avec --lire.", file=sys.stderr)
        return 2
    c = courbe(reponse)
    if len(c) < 10:
        print(f"NON MESURABLE : {len(c)} points seulement.", file=sys.stderr)
        return 3
    if args.segment == "papier":
        return papier(c)
    if args.segment == "prospectif":
        return prospectif(c, enregistrer=not args.sans_registre)
    m = M.construire({HLP: c})                       # tronque au verrou, comme toute la famille V
    ks, ret = m["semaines"], m["ret"][0]
    fin_p = (ks + 1) * M.SEMAINE_MS
    if args.segment == "exploration":
        explo = np.isfinite(ret) & (fin_p <= G.SEGMENTS["validation"][0])
    else:                                     # les periodes closes apres le 01/09, avant le verrou
        explo = np.isfinite(ret) & (fin_p > G.SEGMENTS["validation"][0]) & (fin_p <= M.BORNE_MS)
    x = np.clip(ret[explo], -1.0, 1.0)
    import datetime as dt

    jour = lambda ms: dt.datetime.fromtimestamp(int(ms) / 1000, dt.UTC).strftime("%d/%m/%Y")  # noqa: E731
    prix = D.btc_aux_bornes(ks)
    btc = (prix[1:] / prix[:-1] - 1.0)[explo]
    moy, bas, haut = D.ic_moyenne(x)
    ecart = float(x.std(ddof=1))
    ab = D.alpha_beta(x, btc)
    moitie = x.size // 2
    valeur = m["valeur"][0]
    if x.size < 3:
        print(f"  HLP | segment {args.segment} : {x.size} periode(s) -> " + " | ".join(
            f"{jour(k * M.SEMAINE_MS)}->{jour((k + 1) * M.SEMAINE_MS)} : {1e4 * r:+.1f} bps" for k, r in zip(ks[explo], x)))
        if not args.sans_registre:
            G.enregistrer({"hypothese": "V5_depot_dans_HLP", "segment": args.segment, "statut": "VALIDATION",
                           "periodes": [int(k) for k in ks[explo]], "rendements": [float(r) for r in x]})
            print(f"  essai enregistre (total : {G.nombre_d_essais()})")
        return 0
    print(f"  HLP | {len(c)} points bruts, {int(np.isfinite(ret).sum())} periodes de 28 j connues, dont {x.size} en exploration"
          f" ({jour(ks[explo][0] * M.SEMAINE_MS)} -> {jour(fin_p[explo][-1])})")
    print(f"  valeur du vault : de {np.nanmin(valeur[:-1][explo]):,.0f} a {np.nanmax(valeur[:-1][explo]):,.0f} USD")
    print(f"  rendement par periode : {1e4 * moy:.1f} bps  IC95 [{1e4 * bas:.1f} ; {1e4 * haut:.1f}]"
          f"  | annualise {100 * moy * D.PERIODES_PAR_AN:.1f} %  | volatilite {1e4 * ecart:.0f} bps"
          f"  | Sharpe {moy / ecart * np.sqrt(D.PERIODES_PAR_AN):.2f}")
    print(f"  periodes positives : {100 * np.mean(x > 0):.0f} %  | pire periode {100 * x.min():.1f} %  | repli maximal {100 * D.repli_maximal(x):.1f} %")
    if "alpha" in ab:
        print(f"  contre BTC : alpha {1e4 * ab['alpha']:.1f} bps [{1e4 * ab['ic95'][0]:.1f} ; {1e4 * ab['ic95'][1]:.1f}]"
              f"  | beta {ab['beta']:.3f}  | correlation {ab['correlation']:.2f}  (n={ab['n']})")
    print(f"  moities : {1e4 * x[:moitie].mean():.1f} / {1e4 * x[moitie:].mean():.1f} bps par periode")
    par_an = {}
    for k, r in zip(ks[explo], x):
        par_an.setdefault(dt.datetime.fromtimestamp(int(k) * M.SEMAINE_MS / 1000, dt.UTC).year, []).append(r)
    print("  par annee (somme des periodes) : " + " | ".join(f"{a} : {100 * sum(v):.1f} % ({len(v)} p.)" for a, v in sorted(par_an.items())))
    for n_recent in (13, 26):                 # regime recent : description, pas un nouveau critere
        if x.size >= n_recent:
            r_moy, r_bas, r_haut = D.ic_moyenne(x[-n_recent:])
            print(f"  {n_recent} dernieres periodes : {1e4 * r_moy:.1f} bps [{1e4 * r_bas:.1f} ; {1e4 * r_haut:.1f}]"
                  f"  -> {100 * r_moy * D.PERIODES_PAR_AN:.1f} %/an [{100 * r_bas * D.PERIODES_PAR_AN:.1f} ; {100 * r_haut * D.PERIODES_PAR_AN:.1f}]"
                  f"  | positives {100 * np.mean(x[-n_recent:] > 0):.0f} %  | pire {100 * x[-n_recent:].min():.1f} %")
    critere = bas > 0 and "alpha" in ab and ab["ic95"][0] > 0 and x[:moitie].mean() > 0 and x[moitie:].mean() > 0
    print(f"  CRITERE PRE-ENREGISTRE (IC > 0, alpha > 0, deux moities > 0) : {'ATTEINT' if critere else 'NON ATTEINT'}")
    if not args.sans_registre:
        G.enregistrer({"hypothese": "V5_depot_dans_HLP", "segment": "exploration", "statut": "EXPLORATION",
                       "parametres": {"grille_j": 28, "borne": [-1.0, 1.0], "source": "vaultDetails, hors coffre certifie"},
                       "periodes": int(x.size), "moy": moy, "ic95": [bas, haut], "annualise": moy * D.PERIODES_PAR_AN,
                       "sharpe": moy / ecart * np.sqrt(D.PERIODES_PAR_AN), "repli_max": D.repli_maximal(x),
                       "alpha_beta_btc": ab, "moities": [float(x[:moitie].mean()), float(x[moitie:].mean())],
                       "critere_atteint": bool(critere)})
        print(f"  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
