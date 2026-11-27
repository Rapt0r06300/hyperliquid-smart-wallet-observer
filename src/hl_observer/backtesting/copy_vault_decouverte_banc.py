"""Banc a VERITE CONNUE du moteur de decouverte (27/11/2026) : mesurer si une methode decouvre sans fabriquer de faux.

Les mondes gardent les VRAIES decisions et leurs VRAIS predicats ; seuls les rendements nets sont inventes :
  * bruit calibre sur le REEL, horizon par horizon, a trois niveaux (choc du jour, choc (jour, leader), decision), et
    VERIFIE : l'ecart-type journalier de la copie naive synthetique est compare au reel (``verifier_calibrage``) ;
  * monde NUL : esperance nette nulle partout (la moitie des cellules positives par hasard -- le nul le plus dur) ;
  * monde PLANTE : ``delta_bps`` ajoutes aux decisions d'une cellule tiree dans un ensemble de REFERENCE FIXE, le
    meme pour toutes les methodes comparees (sinon chaque methode affronterait des mondes differents).

Une methode n'est remplacee par une voisine (un parametre pres, jamais sous les garde-fous) que si celle-ci gele plus
d'avantages plantes SUR LES MEMES MONDES, au test exact apparie (McNemar unilateral, <= 0,10 / nombre de variantes),
sans faux gagnant (FDR et mondes nuls <= 5 %). Si la methode courante fabrique elle-meme des faux : retour arriere.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from hl_observer.backtesting import copy_vault_decouverte as D

SCHEMA = "hypersmart.copy_vault_decouverte_banc.v2"
DEFAUT_HORIZON = {"sd_jour": 40.0, "sd_jour_unite": 40.0, "sd_decision": 120.0}


def _codes(table: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pop = table["population"].to_numpy()
    sel = (pop == "exploration") | (pop == "validation")
    return sel, table["jour"].to_numpy(dtype=np.int64), pd.factorize(table["unit"])[0]


def calibrer_banc(table: pd.DataFrame, config: D.DecouverteConfig) -> dict[str, Any]:
    """Variances a trois niveaux du net « suivre » reel (selection), par horizon : jour, (jour, leader), decision."""
    sel, jour, unite = _codes(table)
    par_h: dict[str, dict[str, float]] = {}
    for h in config.horizons_h:
        x = table[f"net_suivre_{h}h"].to_numpy(dtype=float)
        m = sel & np.isfinite(x)
        if m.sum() < 50:
            par_h[str(h)] = {**DEFAUT_HORIZON, "source": "defaut"}
            continue
        j, u, v = jour[m], unite[m], x[m]
        base = int(u.max()) + 1
        cles, inv = np.unique(j * base + u, return_inverse=True)
        n_du = np.bincount(inv)
        m_du = np.bincount(inv, weights=v) / n_du
        ddl = int((n_du - 1).sum())
        var_e = float(np.bincount(inv, weights=(v - m_du[inv]) ** 2).sum() / ddl) if ddl > 0 else float(np.var(v))
        jours_du, inv2 = np.unique(cles // base, return_inverse=True)
        u_d = np.bincount(inv2)
        m_d = np.bincount(inv2, weights=m_du) / u_d
        ecart = m_du - m_d[inv2]
        plusieurs = u_d[inv2] > 1
        corr = ecart[plusieurs] ** 2 / (1.0 - 1.0 / u_d[inv2][plusieurs]) if plusieurs.any() else np.array([0.0])
        var_du = max(0.0, float(corr.mean()) - float(np.mean(var_e / n_du)))
        contrib = np.bincount(inv2, weights=var_du + var_e / n_du) / u_d / u_d
        var_d = max(0.0, float(np.var(m_d, ddof=1)) - float(contrib.mean())) if m_d.size > 1 else DEFAUT_HORIZON["sd_jour"] ** 2
        par_h[str(h)] = {"sd_jour": math.sqrt(var_d), "sd_jour_unite": math.sqrt(var_du), "sd_decision": math.sqrt(var_e),
                         "sd_jour_reel_naif": float(np.std(m_d, ddof=1)) if m_d.size > 1 else None,
                         "source": "reel, selection"}
    calibrage = {"par_horizon": par_h}
    # 27/11 : les queues epaisses faussent la decomposition (sur le reel : niveaux jour et (jour, leader) estimes a 0,
    # copie naive synthetique 65 % trop bruitee a 24 h). On RECALE donc l'ecart-type journalier de la copie naive --
    # la grandeur qui decide de la detection -- sur le reel, par un facteur commun aux trois niveaux (2 passes).
    for _ in range(2):
        verif = verifier_calibrage(table, config, calibrage)
        for h, v in verif.items():
            if v["reel"] and v["synthetique"] and par_h[h].get("source") != "defaut":
                f = v["reel"] / v["synthetique"]
                for k in ("sd_jour", "sd_jour_unite", "sd_decision"):
                    par_h[h][k] *= f
                par_h[h]["source"] = "reel, selection, recale sur l'ecart-type journalier de la copie naive"
    return calibrage


def monde_synthetique(table: pd.DataFrame, config: D.DecouverteConfig, *, graine: int, calibrage: Mapping[str, Any],
                      plantee: Mapping[str, Any] | None = None, delta_bps: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(graine)
    monde = table.copy()
    _, jour, unite = _codes(monde)
    uj, inv_j = np.unique(jour, return_inverse=True)
    base = int(unite.max()) + 1 if unite.size else 1
    udu, inv_du = np.unique(jour * base + unite, return_inverse=True)
    cache: dict = {}
    for h in config.horizons_h:
        p = calibrage.get("par_horizon", {}).get(str(h), DEFAUT_HORIZON)
        for direction in D.DIRECTIONS:
            net = (rng.normal(0.0, p["sd_jour"], uj.size)[inv_j] + rng.normal(0.0, p["sd_jour_unite"], udu.size)[inv_du]
                   + rng.standard_t(3, len(monde)) * p["sd_decision"] / math.sqrt(3.0))
            if plantee is not None and int(plantee["horizon_h"]) == h and plantee["direction"] == direction:
                net = net + np.where(D.masque_cellule(monde, plantee, cache), delta_bps, 0.0)
            monde[f"net_{direction}_{h}h"] = net
    return monde


def verifier_calibrage(table: pd.DataFrame, config: D.DecouverteConfig, calibrage: Mapping[str, Any], *,
                       graine: int = 1) -> dict[str, Any]:
    """Ecart-type journalier de la copie naive : reel contre un monde nul synthetique (doit etre du meme ordre)."""
    monde = monde_synthetique(table, config, graine=graine, calibrage=calibrage)
    sel, jour, unite = _codes(table)
    sortie = {}
    for h in config.horizons_h:
        reel = D.serie_journaliere(table[f"net_suivre_{h}h"].to_numpy(dtype=float), jour, unite, sel)[1]
        synth = D.serie_journaliere(monde[f"net_suivre_{h}h"].to_numpy(dtype=float), jour, unite, sel)[1]
        sortie[str(h)] = {"reel": float(np.std(reel, ddof=1)) if reel.size > 1 else None,
                          "synthetique": float(np.std(synth, ddof=1)) if synth.size > 1 else None}
    return sortie


def cellules_reference(table: pd.DataFrame, config: D.DecouverteConfig, *, min_jours: int = 20) -> list[dict[str, Any]]:
    """Ensemble FIXE de cellules plantables (independant des methodes comparees) : assez couvertes pour etre vues."""
    sel, jour, _ = _codes(table)
    eligibles = []
    for c in D.generer_cellules(D.Methode(), config, graine=0):
        if c["predicats"]:
            m = D.masque_cellule(table, c) & sel
            if m.sum() >= 0.02 * sel.sum() and np.unique(jour[m]).size >= min_jours:
                eligibles.append(c)
    return eligibles


def tirer_plantees(reference: Sequence[Mapping[str, Any]], graines: Sequence[int]) -> list[Mapping[str, Any]]:
    return [reference[int(np.random.default_rng(10_000 + int(g)).integers(0, len(reference)))] for g in graines]


def _jaccard(a: np.ndarray, b: np.ndarray) -> float:
    union = int((a | b).sum())
    return int((a & b).sum()) / union if union else 0.0


def evaluer_methode(table: pd.DataFrame, methode: D.Methode, config: D.DecouverteConfig, *, graines: Sequence[int],
                    plantees: Sequence[Mapping[str, Any]], calibrage: Mapping[str, Any],
                    delta_bps: float = 40.0, juge: Any = None, generer: Any = None) -> dict[str, Any]:
    """Rappel (cellule plantee gelee) et fausses decouvertes, sur des mondes FOURNIS (les memes pour toutes les methodes).

    ``juge`` / ``generer`` : par defaut ceux du moteur courant ; une AUTRE version du juge peut etre passee pour mesurer,
    sur les memes mondes, si une version nouvelle decouvre mieux que l'ancienne (progres prouve, pas affirme)."""
    juge = juge or D.juger_campagne
    generer = generer or D.generer_cellules
    if not plantees:
        return {"rappel": None, "fdr": None, "mondes_nuls_avec_faux": None, "raison": "aucune cellule plantable",
                "touches_par_monde": []}
    sel, _, _ = _codes(table)
    cellules = generer(methode, config, graine=0)
    touches, faux, geles_total, nuls_faux, par_monde = 0, 0, 0, 0, []
    for g, plantee in zip(graines, plantees):
        mp = D.masque_cellule(table, plantee) & sel
        monde = monde_synthetique(table, config, graine=int(g), calibrage=calibrage, plantee=plantee, delta_bps=delta_bps)
        r = juge(monde, cellules, methode, config, rapide=True)
        geles_total += len(r["geles"])
        trouve = False
        for x in r["geles"]:
            meme = (x["direction"], x["horizon_h"]) == (plantee["direction"], plantee["horizon_h"])
            j = _jaccard(D.masque_cellule(monde, x) & sel, mp) if meme else 0.0
            if j >= 0.5:
                trouve = True
            elif j < 0.2:
                faux += 1
        touches += trouve
        par_monde.append(bool(trouve))
        nul = juge(monde_synthetique(table, config, graine=int(g) + 7_777, calibrage=calibrage), cellules,
                   methode, config, rapide=True)
        geles_total += len(nul["geles"])
        faux += len(nul["geles"])
        nuls_faux += bool(nul["geles"])
    return {"rappel": touches / len(graines), "fdr": faux / geles_total if geles_total else 0.0,
            "mondes_nuls_avec_faux": nuls_faux / len(graines), "mondes": len(graines), "delta_bps": delta_bps,
            "n_cellules": len(cellules), "touches_par_monde": par_monde}


def p_apparie(meilleure: Sequence[bool], reference: Sequence[bool]) -> float:
    """Test exact apparie (McNemar unilateral) : P(au moins b succes sur b + c paires discordantes | p = 1/2)."""
    b = sum(1 for x, y in zip(meilleure, reference) if x and not y)
    c = sum(1 for x, y in zip(meilleure, reference) if y and not x)
    n = b + c
    if n == 0:
        return 1.0
    return float(sum(math.comb(n, k) for k in range(b, n + 1)) / 2 ** n)


def puissance(table: pd.DataFrame, methode: D.Methode, config: D.DecouverteConfig, *, graines: Sequence[int],
              deltas: Sequence[float] = (40.0, 80.0, 160.0), calibrage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Ce que le labo SAIT voir : rappel par taille d'avantage plante ; effet minimal detectable (rappel >= 80 %)."""
    calibrage = calibrage if calibrage is not None else calibrer_banc(table, config)
    plantees = tirer_plantees(cellules_reference(table, config), graines) if graines else []
    courbe = {}
    for d in deltas:
        e = evaluer_methode(table, methode, config, graines=graines, plantees=plantees, calibrage=calibrage,
                            delta_bps=float(d))
        courbe[str(int(d))] = {k: e[k] for k in ("rappel", "fdr", "mondes_nuls_avec_faux")}
    detectables = [float(d) for d in deltas if (courbe[str(int(d))]["rappel"] or 0) >= 0.8]
    return {"courbe": courbe, "effet_minimal_detectable_bps": min(detectables) if detectables else None,
            "mondes": len(graines)}


def voisines(m: D.Methode) -> list[D.Methode]:
    """Variantes a UN parametre pres, toutes dans les garde-fous (jamais plus laxistes que les seuils fixes)."""
    options = {"profondeur": (1, 2), "predicats_croises": (4, 6, 8), "explo_min_jours": (20, 30),
               "dsr_seuil": (0.95, 0.975), "pbo_max": (0.5, 0.4)}
    sortie = []
    for champ, valeurs in options.items():
        for v in valeurs:
            if getattr(m, champ) != v:
                n = replace(m, **{champ: v}, version=m.version + 1)
                if n.respecte_les_garde_fous():
                    sortie.append(n)
    return sortie


def ameliorer_methode(table: pd.DataFrame, courante: D.Methode, config: D.DecouverteConfig, *, version_banc: int,
                      mondes: int = 12, fdr_max: float = 0.05, marge_rappel: float = 0.05, delta_bps: float = 40.0,
                      calibrage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Courante contre voisines, sur des mondes NEUFS (graines jamais servies) et IDENTIQUES pour toutes."""
    graines = list(range(version_banc * 1000, version_banc * 1000 + mondes))
    calibrage = calibrage if calibrage is not None else calibrer_banc(table, config)
    plantees = tirer_plantees(cellules_reference(table, config), graines)
    base = evaluer_methode(table, courante, config, graines=graines, plantees=plantees, calibrage=calibrage,
                           delta_bps=delta_bps)
    essais = [(v, evaluer_methode(table, v, config, graines=graines, plantees=plantees, calibrage=calibrage,
                                  delta_bps=delta_bps)) for v in voisines(courante)]
    sures = [(v, e) for v, e in essais if e["rappel"] is not None and e["fdr"] <= fdr_max
             and e["mondes_nuls_avec_faux"] <= fdr_max]
    courante_sure = base["rappel"] is not None and base["fdr"] <= fdr_max and base["mondes_nuls_avec_faux"] <= fdr_max
    choix, decision = courante, ("CONSERVEE" if courante_sure else "AUCUNE_VARIANTE_SURE")
    if not courante_sure and sures:
        choix, _ = min(sures, key=lambda ve: (ve[1]["fdr"], -ve[1]["rappel"], ve[0].version))
        decision = "RETOUR_ARRIERE"
    elif courante_sure:
        seuil_p = 0.10 / max(1, len(essais))           # Bonferroni : alpha 0,10 pour toute la famille de variantes
        meilleures = []
        for v, e in sures:
            e["p_apparie_contre_courante"] = p_apparie(e["touches_par_monde"], base["touches_par_monde"])
            if e["rappel"] >= base["rappel"] + marge_rappel and e["p_apparie_contre_courante"] <= seuil_p:
                meilleures.append((v, e))
        if meilleures:
            choix, _ = max(meilleures, key=lambda ve: (ve[1]["rappel"], -ve[1]["fdr"], -ve[0].version))
            decision = "ADOPTEE"
        elif any(e["rappel"] >= base["rappel"] + marge_rappel for _, e in sures):
            decision = "CONSERVEE_GAIN_NON_SIGNIFICATIF"
    return {"schema": SCHEMA, "decision": decision, "methode_retenue": choix.as_dict(), "courante": courante.as_dict(),
            "banc_courante": base, "variantes": [{"methode": v.as_dict(), "banc": e} for v, e in essais],
            "graines": [graines[0], graines[-1]], "version_banc": version_banc, "calibrage": calibrage,
            "verification_calibrage": verifier_calibrage(table, config, calibrage), "delta_plante_bps": delta_bps,
            "cellules_plantees": [p["id"] for p in plantees], "juge_version": D.JUGE_VERSION}


__all__ = ["SCHEMA", "ameliorer_methode", "calibrer_banc", "cellules_reference", "evaluer_methode", "monde_synthetique",
           "p_apparie", "puissance", "tirer_plantees", "verifier_calibrage", "voisines"]
