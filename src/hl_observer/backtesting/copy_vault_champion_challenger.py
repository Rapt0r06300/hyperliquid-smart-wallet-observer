"""Champion / challenger PAPER du moteur de decouverte (27/11/2026) : promotion, derive, invalidation, retour arriere.

Le champion par defaut est ``AUCUN_TRADE`` : ne rien faire est la reference a battre, jamais une absence de reference.
Un candidat GELE par une campagne n'est juge QUE sur des decisions posterieures a son gel (le suivi), d'un leader deja
suivi a cet instant, et denouees au moment de l'evaluation. Regles fixees ici, avant toute mesure :

  * INVALIDE si, apres au moins 10 jours de suivi, la borne haute de l'IC95 du net journalier est < 0 ;
  * INVALIDE si le test de Page-Hinkley detecte une DERIVE (le net de suivi decroche de la moyenne qui a fait geler) ;
  * PROMU si au moins 30 jours de suivi, borne basse de l'IC95 > 0, retenu par Benjamini-Hochberg (q = 0,10) parmi
    TOUS les challengers actifs, et meilleur que le champion en place sur les memes jours (ecart journalier apparie) ;
  * un champion invalide est remplace par le precedent (pile), et a defaut par ``AUCUN_TRADE`` : retour arriere.

Rien n'est jamais applique au moteur : la sortie est une RECOMMANDATION PAPER ; le cliquet labo -> moteur reste
``copy_vault_champion_deploye`` et la main de Florent.

Les recus du depot sont EMIS, pas reecrits : ``forward_freeze_receipt`` (aucune decision de suivi anterieure au gel)
et ``champion_drift_receipt`` (moyenne de suivi contre la moyenne qui a fait geler), de ``copy_vault_scientific_controls``.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from hl_observer.backtesting import copy_vault_decouverte as D
from hl_observer.backtesting.copy_vault_scientific_controls import champion_drift_receipt, forward_freeze_receipt

SCHEMA = "hypersmart.copy_vault_champion_challenger.v1"
AUCUN_TRADE = "AUCUN_TRADE"
INVALIDE_APRES_JOURS = 10
PH_DELTA_ECARTS = 0.25          # marge toleree, en ecarts-types de reference
PH_LAMBDA_ECARTS = 5.0          # seuil d'alarme, en ecarts-types de reference


def etat_initial() -> dict[str, Any]:
    return {"schema": SCHEMA, "champion": AUCUN_TRADE, "pile_champions": [], "challengers": {}, "journal": []}


def enregistrer_geles(etat: Mapping[str, Any], geles: Sequence[Mapping[str, Any]], *, gel_ms: int,
                      campagne: str, methode_version: int, palier: str = "CANDIDAT") -> dict[str, Any]:
    """Ajoute les nouveaux gels. Un candidat DEJA gele garde sa date d'origine (son suivi ne repart jamais de zero)."""
    nouvel = json.loads(json.dumps(etat))
    for g in geles:
        if g["id"] in nouvel["challengers"]:
            continue
        e = g.get("selection") or g.get("exploration") or {}
        nouvel["challengers"][g["id"]] = {
            "id": g["id"], "direction": g["direction"], "horizon_h": int(g["horizon_h"]),
            "predicats": [list(p) for p in g["predicats"]], "gel_ms": int(gel_ms), "campagne": campagne,
            "methode_version": int(methode_version), "etat": "GELE",
            "reference_moyenne_bps": e.get("moyenne_bps"), "reference_ecart_bps": e.get("ecart_bps"),
            "dsr_au_gel": g.get("dsr"), "palier": palier}
        nouvel["journal"].append({"ts_ms": int(gel_ms), "evenement": "GEL", "id": g["id"], "campagne": campagne,
                                  "palier": palier})
    return nouvel


def page_hinkley(x: Sequence[float], *, reference: float, ecart: float) -> dict[str, Any]:
    """Alarme de baisse de moyenne : m_t = somme(x - reference + delta), alarme si max(m) - m_t > lambda."""
    if not x or not (isinstance(ecart, (int, float)) and math.isfinite(ecart) and ecart > 0) or reference is None:
        return {"alarme": False, "statistique": None}
    delta, lam = PH_DELTA_ECARTS * ecart, PH_LAMBDA_ECARTS * ecart
    m, haut, stat, jour_alarme = 0.0, 0.0, 0.0, None
    for i, v in enumerate(x):
        m += float(v) - float(reference) + delta
        haut = max(haut, m)
        stat = haut - m
        if stat > lam and jour_alarme is None:
            jour_alarme = i
    return {"alarme": jour_alarme is not None, "statistique": stat, "jour_alarme": jour_alarme, "seuil": lam}


def masque_de_suivi(table: pd.DataFrame, challenger: Mapping[str, Any], *, now_ms: int) -> np.ndarray:
    """Decisions de SUIVI : apres le gel, leader deja suivi a cet instant, denouees, mesurables."""
    if not len(table):
        return np.zeros(0, dtype=bool)
    h = int(challenger["horizon_h"])
    t0 = table["t0"].to_numpy(dtype=np.int64)
    suivi = table["entree_suivi"].to_numpy(dtype=np.int64)
    sortie = table["entree"].to_numpy(dtype=np.int64) + h * D.HEURE_MS
    valeurs = table[f"net_{challenger['direction']}_{h}h"].to_numpy(dtype=float)
    return (D.masque_cellule(table, challenger) & (t0 > int(challenger["gel_ms"])) & (suivi > 0) & (t0 >= suivi)
            & (sortie <= int(now_ms)) & np.isfinite(valeurs))


def serie_de_suivi(table: pd.DataFrame, challenger: Mapping[str, Any], *, now_ms: int) -> tuple[np.ndarray, np.ndarray]:
    """Net journalier du challenger sur ses decisions de SUIVI."""
    if not len(table):
        return np.array([], dtype=np.int64), np.array([])
    m = masque_de_suivi(table, challenger, now_ms=now_ms)
    valeurs = table[f"net_{challenger['direction']}_{int(challenger['horizon_h'])}h"].to_numpy(dtype=float)
    return D.serie_journaliere(valeurs, table["jour"].to_numpy(dtype=np.int64), pd.factorize(table["unit"])[0], m)


def evaluer(etat: Mapping[str, Any], table: pd.DataFrame, *, now_ms: int,
            config: D.DecouverteConfig | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Une passe de suivi : mesure chaque challenger actif, invalide, promeut, ou revient en arriere."""
    config = config or D.DecouverteConfig()
    nouvel = json.loads(json.dumps(etat))
    evenements: list[dict[str, Any]] = []
    series: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    actifs = [c for c in nouvel["challengers"].values() if c["etat"] in ("GELE", "SUIVI", "CHAMPION")]
    for c in actifs:
        jours, x = serie_de_suivi(table, c, now_ms=now_ms)
        series[c["id"]] = (jours, x)
        c["suivi"] = D.resumer(x, config)
        c["derive"] = page_hinkley(x.tolist(), reference=c.get("reference_moyenne_bps"),
                                   ecart=c.get("reference_ecart_bps"))
        t_suivi = table["t0"].to_numpy(dtype=np.int64)[masque_de_suivi(table, c, now_ms=now_ms)] if len(table) else []
        c["recus"] = {
            "forward_freeze": forward_freeze_receipt([{"signal_ts_ms": int(t)} for t in t_suivi],
                                                    freeze_ts_ms=int(c["gel_ms"])),
            "champion_drift": champion_drift_receipt([float(c["reference_moyenne_bps"])] if c.get("reference_moyenne_bps") is not None else [],
                                                      x.tolist()),
        }
        n, ic = c["suivi"].get("n_jours", 0), c["suivi"].get("ic95")
        raison = None
        if n >= INVALIDE_APRES_JOURS and ic and ic[1] < 0:
            raison = f"perd en suivi : IC95 [{ic[0]:+.1f} ; {ic[1]:+.1f}] bps sur {n} jours"
        elif n >= INVALIDE_APRES_JOURS and c["derive"]["alarme"]:
            raison = f"derive (Page-Hinkley) au jour {c['derive']['jour_alarme']} du suivi"
        if raison:
            ancien = c["etat"]
            c["etat"], c["raison"] = "INVALIDE", raison
            evenements.append({"ts_ms": int(now_ms), "evenement": "INVALIDATION", "id": c["id"], "raison": raison})
            if ancien == "CHAMPION" or nouvel["champion"] == c["id"]:
                precedent = nouvel["pile_champions"].pop() if nouvel["pile_champions"] else AUCUN_TRADE
                nouvel["champion"] = precedent
                if precedent != AUCUN_TRADE and precedent in nouvel["challengers"]:
                    nouvel["challengers"][precedent]["etat"] = "CHAMPION"
                evenements.append({"ts_ms": int(now_ms), "evenement": "RETOUR_ARRIERE", "id": c["id"],
                                   "nouveau_champion": precedent})
        elif c["etat"] == "GELE" and n > 0:
            c["etat"] = "SUIVI"
    # promotion : au plus un par passe, retenu par BH parmi tous les challengers encore actifs
    candidats = [c for c in nouvel["challengers"].values() if c["etat"] in ("GELE", "SUIVI")]
    p = {c["id"]: c["suivi"]["p_un_cote"] for c in candidats if "p_un_cote" in c.get("suivi", {})}
    retenus = D.benjamini_hochberg(p, D.GARDE_FOUS["q_fdr"]) if p else set()
    eligibles = []
    for c in candidats:
        s = c.get("suivi", {})
        if (c["id"] in retenus and s.get("n_jours", 0) >= D.GARDE_FOUS["forward_min_jours"]
                and s.get("ic95") and s["ic95"][0] > 0
                and _bat_le_champion(c, nouvel, series, config)):
            eligibles.append(c)
    if eligibles:
        gagnant = max(eligibles, key=lambda c: (c["suivi"]["ic95"][0], c["id"]))
        if nouvel["champion"] != AUCUN_TRADE and nouvel["champion"] in nouvel["challengers"]:
            nouvel["challengers"][nouvel["champion"]]["etat"] = "DETRONE"
        nouvel["pile_champions"].append(nouvel["champion"])
        nouvel["champion"] = gagnant["id"]
        gagnant["etat"] = "CHAMPION"
        evenements.append({"ts_ms": int(now_ms), "evenement": "PROMOTION", "id": gagnant["id"],
                           "suivi": gagnant["suivi"]})
    nouvel["journal"].extend(evenements)
    nouvel["recommandation_paper"] = {
        "champion": nouvel["champion"], "applique_au_moteur": False,
        "raison": "PAPER : jamais applique automatiquement ; le cliquet labo -> moteur reste copy_vault_champion_deploye",
        "evalue_a_ms": int(now_ms)}
    return nouvel, evenements


def _bat_le_champion(c: Mapping[str, Any], etat: Mapping[str, Any], series: Mapping[str, Any],
                     config: D.DecouverteConfig) -> bool:
    """Contre AUCUN_TRADE : la borne basse > 0 suffit. Contre un champion : ecart journalier APPARIE, borne basse > 0."""
    champion = etat["champion"]
    if champion == AUCUN_TRADE or champion not in series:
        return True
    jc, xc = series[c["id"]]
    jh, xh = series[champion]
    communs, ic, ih = np.intersect1d(jc, jh, return_indices=True)
    if communs.size < D.GARDE_FOUS["forward_min_jours"]:
        return False
    r = D.resumer(xc[ic] - xh[ih], config)
    return bool(r.get("ic95") and r["ic95"][0] > 0)


__all__ = ["AUCUN_TRADE", "SCHEMA", "enregistrer_geles", "etat_initial", "evaluer", "masque_de_suivi", "page_hinkley",
           "serie_de_suivi"]
