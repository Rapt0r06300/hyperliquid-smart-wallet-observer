"""Planificateur de recherche : quelle expérience mérite la suite, et combien de données lui manquent ?

Le registre des expériences dit, pour chaque hypothèse, un statut. Il ne dit pas laquelle regarder
ensuite. Ce module lit le DERNIER enregistrement de chaque hypothèse et calcule, sans modèle ni
appel extérieur, de quoi décider :

* l'effet mesuré et son incertitude (ramenés à des USD par jour pour 350 USD quand c'est possible) ;
* la probabilité que l'effet soit positif — d'abord telle que les données la donnent, puis avec un
  a priori SCEPTIQUE centré sur zéro (une stratégie de copie rentable est rare : un effet mal
  mesuré est ramené vers zéro d'autant plus que son incertitude est grande) ;
* le nombre de jours de données encore nécessaires pour trancher : celui qu'exige l'étude, et
  celui qu'il faudrait pour que l'intervalle exclue zéro si l'effet restait le même ;
* une priorité = valeur attendue (probabilité sceptique × gain) rapportée au temps d'attente.

Une hypothèse rejetée a une priorité nulle : le calcul va ailleurs. Une hypothèse non mesurable
est listée avec la collecte à activer. Rien ici ne promeut un candidat : le planificateur ordonne
le travail, il ne produit aucune preuve. Déterministe : même registre, même plan.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from scipy.stats import norm

from hl_observer.backtesting.copy_vault_protocol import PAPER_EQUITY_USD

SCHEMA_VERSION = "hypersmart.copy_vault_research_plan.v1"
Z95 = 1.959963984540054
#: écart-type de l'a priori sceptique (centré sur zéro), par unité d'effet
A_PRIORI = {"usd_par_jour": 1.0, "bps_par_jour": 30.0, "bps_par_decision": 20.0}
HORIZON_DE_PATIENCE_JOURS = 30.0
#: au-delà, attendre n'est plus un plan : l'effet est indiscernable de zéro à l'échelle du projet
HORIZON_MAXIMAL_JOURS = 365
LECTURES = ("SIGNAL_PROMETTEUR", "SIGNAL_FRAGILE", "DONNEES_INSUFFISANTES", "ABSENCE_D_AVANTAGE_DEMONTRE")

Preuve = dict[str, Any]


def _depuis_persistance(resume: Mapping[str, Any] | None, config: Mapping[str, Any]) -> Preuve | None:
    if not resume or resume.get("exces_tete_bps_jour") is None:
        return None
    periode = int((config.get("period_days") or [7])[0])
    return {"effet": resume["exces_tete_bps_jour"], "intervalle": resume.get("exces_tete_intervalle_bps_jour"),
            "niveau": resume.get("niveau_intervalle") or 0.95, "unite": "bps_par_jour",
            "usd_par_jour": resume["exces_tete_bps_jour"] / 1e4 * PAPER_EQUITY_USD,
            "jours": int(resume.get("dates") or 0) * periode,
            "jours_requis": int(config.get("min_dates") or 12) * periode,
            "note": "excès brut du meilleur quantile, avant coût de réplication"}


def _persistance(record: Mapping[str, Any]) -> Preuve | None:
    return _depuis_persistance(record.get("primary"), record.get("config") or {})


def _modele(record: Mapping[str, Any]) -> Preuve | None:
    return _depuis_persistance((record.get("leader_model") or {}).get("summary"), record.get("config") or {})


def _replication(record: Mapping[str, Any]) -> Preuve | None:
    resume = record.get("summary") or {}
    if resume.get("net_usd_per_day") is None:
        return {"effet": None, "jours": int(resume.get("distinct_days") or 0), "jours_requis": 20,
                "unite": "usd_par_jour", "note": "aucune journée où le leader est assez observé"}
    return {"effet": resume["net_usd_per_day"], "intervalle": resume.get("interval_95"), "niveau": 0.95,
            "unite": "usd_par_jour", "usd_par_jour": resume["net_usd_per_day"],
            "jours": int(resume.get("distinct_days") or 0), "jours_requis": 20,
            "note": "net de frais, écart, funding et ordre minimal"}


def _ouvertures(record: Mapping[str, Any]) -> Preuve | None:
    primaire = record.get("primary") or {}
    net = primaire.get("net") or {}
    capital = record.get("capital_350") or {}
    requis = int((record.get("config") or {}).get("min_days") or 30)
    # l'espérance au débit du compte, pas le parcours réalisé sur quelques trades (surtout du hasard)
    usd = capital.get("esperance_usd_par_jour", capital.get("net_usd_par_jour"))
    return {"effet": net.get("moyenne_bps"), "intervalle": net.get("intervalle_bps"),
            "niveau": primaire.get("niveau_intervalle") or 0.95, "unite": "bps_par_decision",
            "usd_par_jour": usd, "jours": int(net.get("jours") or 0),
            "jours_requis": requis, "note": "net de frais et d'écart, décisions observées en direct"}


def _selection(record: Mapping[str, Any]) -> Preuve | None:
    choix = (record.get("selection") or {}).get("primaire") or {}
    retenus = choix.get("retenus") or {}
    net = retenus.get("net") or {}
    capital = choix.get("capital_350") or {}
    return {"effet": net.get("moyenne_bps"), "intervalle": net.get("intervalle_bps"),
            "niveau": retenus.get("niveau_intervalle") or 0.95, "unite": "bps_par_decision",
            "usd_par_jour": capital.get("esperance_usd_par_jour"), "jours": int(net.get("jours") or 0),
            "jours_requis": int((record.get("config") or {}).get("min_days") or 30),
            "note": "leaders retenus sur leurs décisions passées, net de frais et d'écart, observés en direct"}


def _ordres(record: Mapping[str, Any]) -> Preuve | None:
    entrees = record.get("inputs") or {}
    return {"effet": None, "unite": "part_du_notionnel", "jours": int(entrees.get("jours") or 0),
            "jours_requis": int((record.get("config") or {}).get("min_days") or 5),
            "note": "précondition d'information (part des exécutions visible à l'avance), pas un gain"}


EXTRACTEURS: dict[str, Callable[[Mapping[str, Any]], Preuve | None]] = {
    "copy_vault_leader_skill_persistence": _persistance,
    "copy_vault_leader_selection_model": _modele,
    "copy_vault_slow_replication_350usd": _replication,
    "copy_vault_aggressive_open_drift": _ouvertures,
    "copy_vault_aggressive_open_selected_leaders": _selection,
    "copy_vault_leader_order_intent": _ordres,
}
ACTIONS = {
    "REJECTED": "abandonner : ne plus y consacrer de calcul ; garder le résultat comme connaissance acquise",
    "PROVEN": "confier au moteur PAPER en marche avant ; ne plus modifier le candidat",
    "PROMISING": "geler le candidat tel quel et le confirmer sur des jours NOUVEAUX (jamais ceux qui l'ont fait naître)",
    "UNMEASURABLE": "activer la collecte de la donnée manquante, puis relancer l'étude",
}


def _lecture(preuve: Preuve) -> dict[str, Any]:
    """Probabilités et jours nécessaires tirés d'un effet et de son intervalle (approximation normale)."""
    effet, intervalle = preuve.get("effet"), preuve.get("intervalle")
    sortie: dict[str, Any] = {"p_positif": None, "p_positif_sceptique": None, "jours_pour_trancher": None}
    if effet is None or not intervalle or None in intervalle or any(isinstance(x, float) and math.isnan(x) for x in intervalle):
        return sortie
    z = float(norm.ppf((1.0 + float(preuve.get("niveau") or 0.95)) / 2.0))
    erreur = (float(intervalle[1]) - float(intervalle[0])) / (2.0 * z)
    if not erreur > 0:
        return sortie
    sortie["erreur_type"] = erreur
    sortie["p_positif"] = float(norm.cdf(effet / erreur))
    a_priori = A_PRIORI.get(str(preuve.get("unite")))
    if a_priori:
        poids = a_priori ** 2 / (a_priori ** 2 + erreur ** 2)        # part de l'effet mesuré que l'on croit
        sortie["p_positif_sceptique"] = float(norm.cdf(effet * math.sqrt(poids) / erreur))
        sortie["effet_sceptique"] = float(effet * poids)
    jours = int(preuve.get("jours") or 0)
    if effet != 0 and jours > 0:
        sortie["jours_pour_trancher"] = int(math.ceil(jours * (Z95 * erreur / abs(effet)) ** 2))
    return sortie


def build_plan(records: Iterable[Mapping[str, Any]], *, capital_usd: float = PAPER_EQUITY_USD) -> dict[str, Any]:
    """Plan de recherche depuis les enregistrements du registre (dans l'ordre d'écriture)."""
    derniers: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    essais: dict[str, int] = {}
    for record in records:
        for verdict in record.get("verdicts") or ():
            hypothese = str(verdict.get("hypothesis") or "")
            if hypothese:
                derniers[hypothese] = (record, verdict)
                essais[hypothese] = essais.get(hypothese, 0) + 1
    lignes: list[dict[str, Any]] = []
    for hypothese, (record, verdict) in derniers.items():
        statut = str(verdict.get("status") or "")
        extracteur = EXTRACTEURS.get(hypothese)
        preuve = (extracteur(record) if extracteur else None) or {}
        mesure = _lecture(preuve)
        jours, requis = int(preuve.get("jours") or 0), int(preuve.get("jours_requis") or 0)
        cible = max(requis, mesure["jours_pour_trancher"] or 0)
        restants = max(0, cible - jours) if (requis or mesure["jours_pour_trancher"]) else None
        usd = preuve.get("usd_par_jour")
        if usd is not None and mesure.get("effet_sceptique") is not None and preuve.get("effet"):
            usd_sceptique = float(usd) * mesure["effet_sceptique"] / float(preuve["effet"])
        else:
            usd_sceptique = None
        priorite = 0.0
        if statut not in ("REJECTED", "UNMEASURABLE") and usd_sceptique is not None and mesure["p_positif_sceptique"] is not None:
            attente = 1.0 + (restants or 0) / HORIZON_DE_PATIENCE_JOURS
            priorite = mesure["p_positif_sceptique"] * max(0.0, usd_sceptique) / attente
        # Lecture en quatre cas : prometteur, fragile, données insuffisantes, absence d'avantage démontré.
        echantillon_atteint = bool(requis) and jours >= requis
        if statut in ("PROVEN", "PROMISING"):
            lecture = LECTURES[0]
        elif statut == "REJECTED":
            lecture = LECTURES[3]
        elif echantillon_atteint and mesure["p_positif"] is not None and (
                mesure["p_positif"] <= 0.05 or (mesure["jours_pour_trancher"] or 0) > HORIZON_MAXIMAL_JOURS):
            # échantillon exigé atteint, et l'effet est soit nettement négatif, soit trop proche de zéro
            # pour être tranché avant des années : attendre n'apprendrait rien d'utile
            lecture = LECTURES[3]
        elif priorite > 0 and (mesure["p_positif_sceptique"] or 0.0) >= 0.75:
            lecture = LECTURES[1]
        else:
            lecture = LECTURES[2]
        if statut == "MORE_DATA" and lecture == LECTURES[3]:
            action = ("ne pas attendre : avec l'échantillon exigé déjà atteint, l'effet mesuré reste indiscernable "
                      "de zéro (ou négatif) ; chercher un autre mécanisme plutôt que plus de jours")
        elif statut == "MORE_DATA":
            action = (f"attendre environ {restants} jour(s) de données de plus, puis relancer l'étude"
                      if restants else "relancer l'étude : l'échantillon exigé est atteint, l'intervalle ne tranche pas encore")
        else:
            action = ACTIONS.get(statut, "relancer l'étude")
        lignes.append({
            "hypothesis": hypothese, "status": statut, "lecture": lecture, "reason": verdict.get("reason"),
            "run_id": record.get("run_id"), "evidence_tier": record.get("evidence_tier"),
            "essais_enregistres": essais[hypothese],
            "effet": preuve.get("effet"), "intervalle": preuve.get("intervalle"), "unite": preuve.get("unite"),
            "usd_par_jour": usd, "usd_par_jour_sceptique": usd_sceptique, "note": preuve.get("note"),
            "p_positif": mesure["p_positif"], "p_positif_sceptique": mesure["p_positif_sceptique"],
            "jours_mesures": jours, "jours_requis": requis or None,
            "jours_pour_trancher": mesure["jours_pour_trancher"], "jours_restants": restants,
            "priorite": round(priorite, 6), "action": action,
        })
    # priorité d'abord ; à priorité égale, ce qui peut encore apprendre quelque chose le plus vite
    lignes.sort(key=lambda ligne: (-ligne["priorite"], LECTURES.index(ligne["lecture"]),
                                   ligne["jours_restants"] if ligne["jours_restants"] is not None else 10 ** 9,
                                   ligne["hypothesis"]))
    return {
        "schema_version": SCHEMA_VERSION, "capital_usd": capital_usd,
        "a_priori_sceptique": A_PRIORI, "horizon_de_patience_jours": HORIZON_DE_PATIENCE_JOURS,
        "hypotheses": lignes,
        "resume": {statut: sum(1 for ligne in lignes if ligne["status"] == statut)
                   for statut in ("PROVEN", "PROMISING", "MORE_DATA", "UNMEASURABLE", "REJECTED")},
        "prochaine_action": lignes[0]["hypothesis"] if lignes and lignes[0]["priorite"] > 0 else None,
        "paper_read_only": True, "real_execution": False, "economically_proven": False,
    }


def render_plan(plan: Mapping[str, Any]) -> str:
    def num(value: Any, digits: int = 2, signe: bool = True) -> str:
        if value is None:
            return "n/d"
        return f"{float(value):+.{digits}f}" if signe else f"{float(value):.{digits}f}"

    resume = plan["resume"]
    lignes = [
        "# Plan de recherche Copy-Vault", "",
        "Classement des hypothèses par valeur attendue rapportée au temps d'attente. Ce plan ordonne le "
        "travail ; il ne prouve rien et ne promeut aucun candidat.", "",
        "- " + " · ".join(f"{statut} : {n}" for statut, n in resume.items()) + ".",
        f"- Probabilité « sceptique » : a priori centré sur zéro (écart-type {plan['a_priori_sceptique']}).", "",
        "| rang | hypothèse | statut | lecture | effet mesuré | USD/jour (350 USD) | P(effet > 0) | P sceptique | jours mesurés | jours restants | priorité |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rang, h in enumerate(plan["hypotheses"], 1):
        effet = "n/d" if h["effet"] is None else f"{num(h['effet'])} {str(h['unite']).replace('_', ' ')}"
        lignes.append(
            f"| {rang} | `{h['hypothesis']}` | {h['status']} | {h['lecture'].replace('_', ' ').lower()} | {effet} | "
            f"{num(h['usd_par_jour'], 3)} | "
            f"{num(h['p_positif'], 2, False)} | {num(h['p_positif_sceptique'], 2, False)} | {h['jours_mesures']} | "
            f"{'n/d' if h['jours_restants'] is None else h['jours_restants']} | {h['priorite']:.4f} |")
    lignes += ["", "## Que faire, hypothèse par hypothèse", ""]
    for h in plan["hypotheses"]:
        lignes.append(f"- `{h['hypothesis']}` — **{h['status']}** : {h['action']}."
                      + (f" ({h['note']})" if h.get("note") else ""))
    prochaine = plan.get("prochaine_action")
    lignes += ["", f"Priorité actuelle : `{prochaine}`." if prochaine else
               "Aucune hypothèse n'a aujourd'hui de valeur attendue positive : la priorité est la collecte.", ""]
    return "\n".join(lignes)


__all__ = ["A_PRIORI", "EXTRACTEURS", "LECTURES", "SCHEMA_VERSION", "build_plan", "render_plan"]
