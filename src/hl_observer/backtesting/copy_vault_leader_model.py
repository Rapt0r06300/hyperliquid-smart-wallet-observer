"""Modèle de sélection des leaders, appris en marche avant sur plusieurs caractéristiques.

IDÉE. « Copier les gagnants passés » n'utilise qu'une information : le rendement récent. Or les
courbes publiées d'un vault en disent plus, à chaque date et sans rien connaître de l'avenir :
son rendement très récent et plus ancien, sa régularité, son repli depuis son sommet, sa taille,
son ancienneté, et les dépôts / retraits de ses suiveurs. Ce module apprend, sur le PASSÉ
seulement, quelle combinaison de ces caractéristiques a précédé un meilleur rendement, puis note
les vaults pour la période suivante. Le signe de chaque effet (continuation ou retour à la
moyenne) n'est pas supposé : il est appris.

GARDE-FOUS.
* Marche avant stricte : le modèle qui note la période ``t`` n'a vu que des périodes ``< t``
  entièrement terminées. Aucune caractéristique n'utilise une donnée de la période notée.
* Tout est exprimé en RANGS par date (caractéristiques et cible) : un vault aux rendements
  extrêmes ne peut pas, à lui seul, dicter le modèle.
* Un seul modèle, linéaire, pénalité fixée à l'avance : aucun réglage sur les résultats. Il compte
  pour une hypothèse de plus dans la correction de multiplicité.
* Jugé par la même mesure que les autres règles (``copy_vault_persistence.evaluer_notes``) :
  mêmes quantiles, même placebo, mêmes coûts de réplication.

Résultat EXPLORATOIRE (historique relu, univers observé) : jamais une preuve économique.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from scipy.stats import rankdata

from hl_observer.backtesting.copy_vault_persistence import (
    EVIDENCE_TIER,
    SEUIL_ACTIVITE,
    PersistenceConfig,
    evaluer_notes,
    period_returns,
    summarize,
)

H_LEADER_MODEL = "copy_vault_leader_selection_model"
FEATURES = (
    "rendement_1",       # dernière période
    "rendement_4",       # moyenne des 4 dernières
    "rendement_12",      # moyenne des 12 dernières (au moins 6 connues)
    "volatilite_12",     # écart-type des 12 dernières
    "repli",             # écart au sommet du rendement cumulé (0 = au sommet)
    "anciennete",        # nombre de périodes connues
    "taille",            # valeur du compte au début de la période notée (connue à cet instant)
    "flux_4",            # dépôts nets des 4 dernières périodes, rapportés au capital
)


@dataclass(frozen=True, slots=True)
class LeaderModelConfig:
    """Paramètres fixés AVANT la mesure."""

    period_days: int = 7
    ridge_lambda: float = 10.0          # pénalité (en espace de rangs) : fixée, jamais réglée
    min_train_dates: int = 20           # dates d'apprentissage terminées avant la première note
    min_history_periods: int = 4        # un vault n'est noté qu'avec 4 périodes connues juste avant
    n_configurations_totales: int = 28  # 27 règles de performance passée + ce modèle

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_panel(
    curves: Mapping[str, Sequence[tuple[int, float | None, float | None]]], *, period_days: int,
    config: PersistenceConfig | None = None,
) -> dict[str, Any]:
    """Matrices vaults × périodes : rendement, valeur de début, flux net / capital (``NaN`` = inconnu)."""
    config = config or PersistenceConfig()
    par_vault = {vault: period_returns(curve, period_days=period_days, config=config)
                 for vault, curve in sorted(curves.items())}
    periodes = sorted({k for cellules in par_vault.values() for k in cellules})
    vaults = [vault for vault, cellules in par_vault.items() if cellules]
    forme = (len(vaults), len(periodes))
    panel = {"vaults": vaults, "periodes": periodes,
             "ret": np.full(forme, np.nan), "valeur_debut": np.full(forme, np.nan), "flux": np.full(forme, np.nan)}
    colonne = {k: j for j, k in enumerate(periodes)}
    for i, vault in enumerate(vaults):
        for k, cellule in par_vault[vault].items():
            j = colonne[k]
            panel["ret"][i, j] = cellule["ret"]
            panel["valeur_debut"][i, j] = cellule["valeur_debut"]
            panel["flux"][i, j] = cellule["flux_ratio"]
    return panel


def features_at(panel: Mapping[str, Any], t: int, *, min_history: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """``(X, notables)`` à la date ``t``. N'utilise que les colonnes ``< t`` et la valeur de début ``t``.

    Un vault est notable s'il a ses ``min_history`` dernières périodes connues et une valeur de
    compte connue au début de la période notée.
    """
    ret, valeur, flux = panel["ret"], panel["valeur_debut"], panel["flux"]
    n = ret.shape[0]
    X = np.full((n, len(FEATURES)), np.nan)
    if t < min_history:
        return X, np.zeros(n, dtype=bool)
    passe = ret[:, :t]
    recents = passe[:, t - min_history:t]
    notables = ~np.isnan(recents).any(axis=1) & ~np.isnan(valeur[:, t]) & (valeur[:, t] > 0)
    # même univers que l'étude de persistance : un vault sans aucune variation récente n'a rien à copier
    with np.errstate(invalid="ignore"):
        notables &= np.where(notables, recents.std(axis=1, ddof=1), 0.0) > SEUIL_ACTIVITE
    douze = passe[:, max(0, t - 12):t]
    connus_12 = (~np.isnan(douze)).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        moyenne_12 = np.where(connus_12 >= 6, np.nanmean(np.where(connus_12[:, None] >= 6, douze, 0.0), axis=1), np.nan)
        ecart_12 = np.where(connus_12 >= 6, np.nanstd(np.where(connus_12[:, None] >= 6, douze, 0.0), axis=1), np.nan)
    cumul = np.nancumsum(np.where(np.isnan(passe), 0.0, passe), axis=1)
    sommet = np.maximum.accumulate(cumul, axis=1)
    flux_recents = flux[:, t - min_history:t]
    X[:, 0] = passe[:, t - 1]
    X[:, 1] = recents.mean(axis=1)
    X[:, 2] = np.where(np.isnan(moyenne_12), X[:, 1], moyenne_12)      # historique court : repli sur 4 périodes
    X[:, 3] = np.where(np.isnan(ecart_12), recents.std(axis=1), ecart_12)
    X[:, 4] = cumul[:, -1] - sommet[:, -1]
    X[:, 5] = (~np.isnan(passe)).sum(axis=1)
    X[:, 6] = np.log10(np.where(valeur[:, t] > 0, valeur[:, t], np.nan))
    X[:, 7] = np.where(np.isnan(flux_recents).any(axis=1), 0.0, flux_recents.sum(axis=1))
    X[~notables] = np.nan
    return X, notables


def _rangs(valeurs: np.ndarray) -> np.ndarray:
    """Rangs centrés dans ``[-0,5 ; +0,5]`` par colonne (ex æquo au rang moyen)."""
    if valeurs.ndim == 1:
        return (rankdata(valeurs) - 0.5) / valeurs.size - 0.5
    return np.column_stack([(rankdata(valeurs[:, j]) - 0.5) / valeurs.shape[0] - 0.5
                            for j in range(valeurs.shape[1])])


def walk_forward_model(
    panel: Mapping[str, Any], *, config: LeaderModelConfig | None = None,
    persistence: PersistenceConfig | None = None,
) -> tuple[dict[int, np.ndarray], list[dict[str, Any]]]:
    """Notes par date + coefficients appris à chaque date (pour expliquer d'où vient la note).

    À la date ``t`` : on ajoute à l'apprentissage la période ``t-1`` (désormais terminée), on
    résout la régression pénalisée, puis on note ``t``. La période notée n'entre dans
    l'apprentissage qu'à la date suivante.
    """
    config = config or LeaderModelConfig()
    persistence = persistence or PersistenceConfig()
    ret = panel["ret"]
    k = len(FEATURES)
    xtx, xty = np.zeros((k, k)), np.zeros(k)
    appris = 0
    notes_par_date: dict[int, np.ndarray] = {}
    coefficients: list[dict[str, Any]] = []
    for t in range(config.min_history_periods, ret.shape[1]):
        s = t - 1
        if s >= config.min_history_periods:
            X_s, notables_s = features_at(panel, s, min_history=config.min_history_periods)
            utiles = notables_s & ~np.isnan(ret[:, s])
            if int(utiles.sum()) >= persistence.min_vaults_per_date:
                rx, ry = _rangs(X_s[utiles]), _rangs(ret[utiles, s])
                xtx += rx.T @ rx
                xty += rx.T @ ry
                appris += 1
        if appris < config.min_train_dates:
            continue
        X_t, notables_t = features_at(panel, t, min_history=config.min_history_periods)
        if int(notables_t.sum()) < persistence.min_vaults_per_date:
            continue
        beta = np.linalg.solve(xtx + config.ridge_lambda * np.eye(k), xty)
        notes = np.full(ret.shape[0], np.nan)
        notes[notables_t] = _rangs(X_t[notables_t]) @ beta
        notes_par_date[t] = notes
        coefficients.append({"t": t, "dates_apprises": appris, **dict(zip(FEATURES, (float(b) for b in beta), strict=True))})
    return notes_par_date, coefficients


def verdict_modele(resume: Mapping[str, Any], persistence: PersistenceConfig | None = None) -> dict[str, Any]:
    persistence = persistence or PersistenceConfig()
    base = {"hypothesis": H_LEADER_MODEL, "evidence_tier": EVIDENCE_TIER, "economically_proven": False}
    dates = int(resume.get("dates") or 0)
    if dates < persistence.min_dates or resume.get("ic_intervalle") is None:
        return {**base, "status": "MORE_DATA",
                "reason": f"{dates} dates notées ; il en faut au moins {persistence.min_dates}"}
    ic_bas, ic_haut = resume["ic_intervalle"]
    ex_bas, ex_haut = resume["exces_tete_intervalle_bps_jour"]
    net = resume.get("tete_nette_intervalle_bps_jour")
    if ic_bas > 0 and ex_bas > 0 and net is not None and net[0] > 0:
        return {**base, "status": "PROMISING",
                "reason": "le modèle classe correctement les vaults hors apprentissage et l'excès résiste à la borne "
                          "haute du coût de réplication ; à confirmer sur portefeuilles observés et en marche avant réelle"}
    if ic_bas > 0 and ex_bas > 0:
        return {**base, "status": "MORE_DATA",
                "reason": "pouvoir de classement mesuré avant coûts ; le net de réplication n'est pas établi"}
    if ic_haut <= 0 or ex_haut <= 0:
        return {**base, "status": "REJECTED", "reason": "le modèle ne classe pas mieux que le hasard hors apprentissage"}
    if dates >= persistence.dates_for_rejection and ic_haut < persistence.negligible_ic:
        return {**base, "status": "REJECTED",
                "reason": f"pouvoir de classement négligeable (IC < {persistence.negligible_ic}) malgré {dates} dates"}
    return {**base, "status": "MORE_DATA", "reason": "intervalle à cheval sur zéro : l'échantillon ne tranche pas"}


def run_leader_model_study(
    curves: Mapping[str, Sequence[tuple[int, float | None, float | None]]],
    *, turnover_per_day: Mapping[str, float | None] | None = None,
    config: LeaderModelConfig | None = None, persistence: PersistenceConfig | None = None,
) -> dict[str, Any]:
    """Étude complète du modèle : notes en marche avant, mêmes mesures que les règles simples."""
    config = config or LeaderModelConfig()
    persistence = persistence or PersistenceConfig()
    turnover_per_day = turnover_per_day or {}
    panel = build_panel(curves, period_days=config.period_days, config=persistence)
    niveau = 1.0 - (1.0 - persistence.confidence) / config.n_configurations_totales
    base = {"hypothesis": H_LEADER_MODEL, "config": config.as_dict(), "features": list(FEATURES),
            "vaults": len(panel["vaults"]), "periodes": len(panel["periodes"]),
            "paper_read_only": True, "real_execution": False, "economically_proven": False}
    if not panel["vaults"]:
        return {**base, "summary": {"dates": 0}, "coefficients_moyens": {}, "verdict": verdict_modele({"dates": 0})}
    rotation = np.array([np.nan if turnover_per_day.get(v) is None else float(turnover_per_day[v])
                         for v in panel["vaults"]])
    cout = rotation * config.period_days * persistence.cost_bps_per_notional / 1e4
    notes_par_date, coefficients = walk_forward_model(panel, config=config, persistence=persistence)
    lignes = evaluer_notes(panel["ret"], notes_par_date, config=persistence, cout_par_periode=cout)
    resume = summarize(lignes, period_days=config.period_days, niveau=niveau, config=persistence)
    moyens = ({nom: float(np.mean([c[nom] for c in coefficients])) for nom in FEATURES} if coefficients else {})
    stables = ({nom: float(np.mean([np.sign(c[nom]) == np.sign(moyens[nom]) for c in coefficients]))
                for nom in FEATURES} if coefficients else {})
    return {
        **base, "summary": resume, "confidence_after_multiplicity": niveau,
        # effet appris de chaque caractéristique (rangs) : signe > 0 = « plus c'est élevé, mieux le vault
        # a fait ensuite ». La stabilité est la part des dates où le signe est celui de la moyenne.
        "coefficients_moyens": moyens, "stabilite_du_signe": stables,
        "coefficients_derniers": coefficients[-1] if coefficients else None,
        "verdict": verdict_modele(resume, persistence),
    }


__all__ = [
    "FEATURES", "H_LEADER_MODEL", "LeaderModelConfig", "build_panel", "features_at",
    "run_leader_model_study", "verdict_modele", "walk_forward_model",
]
