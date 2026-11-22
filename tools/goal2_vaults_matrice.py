r"""Matrice par periodes de 28 jours des vaults pour la famille V (allocation par depot) -- tronquee A LA SOURCE.

ENTREE. Famille `vault_portfolio` du coffre LOCAL certifie (shards dont le SHA-256 est reverifie
contre l'index par `etude_copiabilite.select_shards`). Les courbes (ts, valeur, PnL cumule) sont
reconstituees par `fusionner_points`, la fonction du depot.

TRONCATURE. Tout point d'instant >= BORNE (debut du segment d'execution, 26/10/2026) est ECARTE
AU CHARGEMENT : l'execution et l'OOS final n'entrent ni dans la matrice ni dans son cache. Une
etude qui importe ce module ne peut donc pas les lire par accident.

GRILLE. Periodes calendaires UTC de 28 jours (indice k = instant // 28 j). Pourquoi 28 : 31 % des
pas de l'historique font 14 jours, sur une parite propre a chaque vault ; une grille de 7 jours ne
connaissait que 17 % des cellules. La valeur a une borne est le dernier point CONNU a cette borne,
vieux d'au plus 7,5 jours ; sinon INCONNUE -- jamais prolongee, jamais interpolee.

RENDEMENT de la periode k = (PnL_{k+1} - PnL_k) / (valeur_k + flux / 2), flux = depots nets
(methode de Dietz, celle du module `copy_vault_persistence`).
EXCEPTION DECLAREE -- periode de CLOTURE : quand la valeur de fin tombe sous 1 % de celle de
debut, tout le capital est sorti et Dietz se deforme (une perte de 20 % y devient -33 %). Le
rendement est alors ΔPnL / valeur de DEBUT : ce qu'a vecu un deposant present depuis la borne.

SORTIES (forme vaults x periodes, NaN = inconnu) : `ret`, `valeur` (aux bornes, une colonne de
plus), `flux_ratio`, `cloture` (booleen) ; et par vault `premier_ms` (premier point de la courbe).
LECTURE SEULE.
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np

import goal2_commun as G

SEMAINE_MS = 28 * G.JOUR_MS          # la PERIODE de la grille (nom garde : une seule constante de pas)
PERIME_MS = int(7.5 * G.JOUR_MS)
SEUIL_CLOTURE = 0.01                 # valeur de fin < 1 % de la valeur de debut
BORNE_MS = G.SEGMENTS["execution"][0]          # rien au-dela n'est charge
CACHE = G.CACHE / "vaults_28j.npz"


def tronquer(courbe, borne_ms: int = BORNE_MS):
    return [p for p in courbe if int(p[0]) < borne_ms]


def aux_bornes(ts: np.ndarray, valeurs: np.ndarray, bornes: np.ndarray) -> np.ndarray:
    """Derniere valeur connue a chaque borne (jamais posterieure), si elle n'est pas perimee."""
    connus = ~np.isnan(valeurs)
    t, v = ts[connus], valeurs[connus]
    sortie = np.full(len(bornes), np.nan)
    if t.size == 0:
        return sortie
    i = np.searchsorted(t, bornes, side="right") - 1
    ok = i >= 0
    j = np.maximum(i, 0)
    ok &= (bornes - t[j]) <= PERIME_MS
    sortie[ok] = v[j[ok]]
    return sortie


def construire(courbes: dict, *, borne_ms: int = BORNE_MS) -> dict:
    """Courbes {vault: [(ts, valeur, pnl)]} -> matrices par periode.

    `borne_ms` vaut le VERROU par defaut. Seule la mesure PROSPECTIVE (periodes posterieures au
    gel de la regle) a le droit d'en passer une autre -- et elle ecarte alors tout le passe.
    """
    courbes = {v: tronquer(c, borne_ms) for v, c in courbes.items()}
    courbes = {v: c for v, c in courbes.items() if len(c) >= 2}
    k_min = min(-(-int(c[0][0]) // SEMAINE_MS) for c in courbes.values())
    # Derniere borne : celle qui SUIT le dernier point, s'il la precede de moins que la peremption.
    # Les points sont publies quelques heures AVANT la borne : s'arreter a `dernier // periode`
    # perdait la derniere periode de chaque serie (trouve par les tests, avant toute mesure).
    # Jamais au-dela du verrou.
    k_max = max((int(c[-1][0]) + PERIME_MS) // SEMAINE_MS for c in courbes.values())
    k_max = min(k_max, borne_ms // SEMAINE_MS)
    ks = np.arange(k_min, k_max + 1, dtype=np.int64)          # bornes
    bornes = ks * SEMAINE_MS
    vaults = sorted(courbes)
    n, m = len(vaults), len(ks) - 1
    valeur = np.full((n, len(ks)), np.nan)
    ret = np.full((n, m), np.nan)
    flux_ratio = np.full((n, m), np.nan)
    cloture = np.zeros((n, m), dtype=bool)
    premier = np.zeros(n, dtype=np.int64)
    for i, vault in enumerate(vaults):
        c = courbes[vault]
        ts = np.array([int(p[0]) for p in c], dtype=np.int64)
        val = np.array([np.nan if p[1] is None else float(p[1]) for p in c])
        pnl = np.array([np.nan if p[2] is None else float(p[2]) for p in c])
        premier[i] = ts[0]
        v_b, p_b = aux_bornes(ts, val, bornes), aux_bornes(ts, pnl, bornes)
        valeur[i] = v_b
        gain = p_b[1:] - p_b[:-1]
        flux = v_b[1:] - v_b[:-1] - gain
        capital = v_b[:-1] + 0.5 * flux
        ok = np.isfinite(gain) & np.isfinite(capital) & (capital > 0) & (v_b[:-1] > 0)
        ret[i, ok] = gain[ok] / capital[ok]
        flux_ratio[i, ok] = flux[ok] / capital[ok]
        ferme = np.isfinite(gain) & (v_b[:-1] > 0) & (v_b[1:] < SEUIL_CLOTURE * v_b[:-1])
        ret[i, ferme] = gain[ferme] / v_b[:-1][ferme]          # periode de cloture : capital de DEBUT
        cloture[i, ferme] = True
    return {"vaults": np.array(vaults), "semaines": ks[:-1], "ret": ret, "valeur": valeur,
            "flux_ratio": flux_ratio, "cloture": cloture, "premier_ms": premier}


def charger_courbes(racine) -> tuple[dict, dict]:
    from etude_copiabilite import load_snapshots, select_shards
    from hl_observer.collection.vault_portfolio_history import fusionner_points

    shards, exclus = select_shards(racine, {"vault_portfolio": ""})
    lignes = list(load_snapshots(shards["vault_portfolio"]))
    fermes = {str(x.get("vault") or "").lower() for x in lignes if x.get("is_closed") is True}
    return fusionner_points(lignes), {"shards": len(shards["vault_portfolio"]), "exclus": len(exclus),
                                      "lignes": len(lignes), "vaults_fermes": len(fermes)}


def matrice(*, reconstruire: bool = False) -> dict:
    """La matrice, depuis le cache s'il existe (il est tronque a la meme borne)."""
    if CACHE.is_file() and not reconstruire:
        z = np.load(CACHE, allow_pickle=False)
        if int(z["borne_ms"]) == BORNE_MS:
            return {k: z[k] for k in z.files}
    courbes, bilan = charger_courbes(G.RACINE)
    m = construire(courbes)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, borne_ms=np.int64(BORNE_MS), **m)
    (CACHE.with_suffix(".json")).write_text(json.dumps({**bilan, "borne_ms": BORNE_MS,
        "vaults": int(len(m["vaults"])), "semaines": int(len(m["semaines"]))}, indent=1), encoding="utf-8")
    return {**m, "borne_ms": np.int64(BORNE_MS)}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--reconstruire", action="store_true")
    args = p.parse_args(argv)
    m = matrice(reconstruire=args.reconstruire)
    import datetime as dt

    jour = lambda k: dt.datetime.fromtimestamp(int(k) * SEMAINE_MS / 1000, dt.UTC).strftime("%d/%m/%Y")  # noqa: E731
    connus = np.isfinite(m["ret"])
    print(f"  {len(m['vaults'])} vaults x {len(m['semaines'])} periodes de 28 j | du {jour(m['semaines'][0])} au {jour(m['semaines'][-1] + 1)}"
          f" | rendements connus : {int(connus.sum()):,} ({100 * connus.mean():.1f} %)")
    borne = dt.datetime.fromtimestamp(BORNE_MS / 1000, dt.UTC).strftime("%d/%m/%Y")
    print(f"  tronque a la source : aucun point >= {borne}")
    par_periode = connus.sum(axis=0)
    print(f"  vaults a rendement connu par periode : mediane {int(np.median(par_periode))}, min {int(par_periode.min())}, max {int(par_periode.max())}"
          f" | periodes de cloture : {int(m['cloture'].sum()):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
