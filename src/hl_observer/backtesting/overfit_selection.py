"""H-181 -- ON SELECTIONNE LES 40 CONFIGS LES PLUS CHANCEUSES, PUIS ON S'ETONNE QU'AUCUNE NE TIENNE.

LE CODE, LIGNE 268 DE `scenario_search.py` :

    scored.sort(key=lambda r: (r[1]["net_total_usd"] or 0.0), reverse=True)
    for sc, train_rep in scored[:top_k]:            # top_k = 40

**Les 40 finalistes sont les 40 meilleurs PnL sur le TRAIN.**

Sur 150 000 000 de configurations, le MAXIMUM du PnL d'entrainement n'est pas la meilleure
config : c'est le maximum d'un BRUIT. Meme si aucune config n'a le moindre edge, la meilleure
des 150 M affichera un train tres positif -- par pure chance. C'est la « malediction du
vainqueur » (winner's curse), et elle est mecanique : plus on teste, plus le maximum monte.

Consequence : on ne teste pas hors echantillon les 40 MEILLEURES configs. On teste les 40 plus
CHANCEUSES. Et une chance ne se reproduit pas. « 0 config robuste sur 150 M » n'est donc peut-etre
pas un resultat sur le marche -- ce serait un resultat sur notre PROPRE procedure de selection.

CE MODULE NE CROIT PAS CETTE HISTOIRE SUR PAROLE. IL LA TESTE.
==============================================================

**Le controle par PERMUTATION** (`borne_du_hasard`). On detruit tout edge eventuel en melangeant
le SENS des trades (LONG <-> SHORT au hasard), ce qui preserve :
  * le nombre de trades,
  * la distribution des mouvements de prix,
  * les couts,
  * la structure des scenarios ;
et ne detruit QUE le lien entre le signal et la direction. Puis on refait TOUTE la selection.

  * Si le max du train REEL ressemble au max du train PERMUTE -> notre top-40 est du bruit pur.
    La procedure de selection est cassee, et « 0 robuste » ne dit rien du marche.
  * Si le max REEL depasse nettement la borne du hasard -> il y a bien quelque chose, et
    « 0 robuste » est un vrai resultat.

C'est la SEULE facon de distinguer les deux, et ca ne coute qu'un second passage.

CE QU'ON PROPOSE A LA PLACE (`selection_par_plateau`)
=====================================================
Ne pas classer une config sur SON PROPRE score, mais sur celui de son VOISINAGE. Un point
chanceux est entoure de mediocres ; un vrai edge est entoure de bons. C'est une selection
ROBUSTE : elle ne peut pas etre gagnee par un coup de chance isole.

⚠️ `_plateau_flag` existe DEJA dans le code -- mais il est utilise APRES coup, comme un filtre
sur les 40 deja retenus par le maximum. Filtrer apres avoir mal choisi ne rattrape rien : si les
40 sont tous chanceux, aucun ne passera le plateau, et on conclura « 0 robuste » sans jamais avoir
regarde les configs qui le meritaient. **Le plateau doit servir a CHOISIR, pas a valider.**

Module PUR : aucune I/O, aucun ordre. Simulation paper uniquement.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence
from typing import Any

SELECTION_MAX = "SELECTION_PAR_MAXIMUM"          # ce que fait le code aujourd'hui
SELECTION_PLATEAU = "SELECTION_PAR_PLATEAU"      # ce qu'on propose

VERDICT_BRUIT = "LE_TOP_EST_INDISCERNABLE_DU_HASARD"
VERDICT_SIGNAL = "LE_TOP_DEPASSE_LA_BORNE_DU_HASARD"
VERDICT_INSUFFISANT = "INSUFFICIENT_DATA"
# 🔴 Le verdict qui compte quand RIEN ne gagne, meme en echantillon : il n'y a pas de vainqueur
# a maudire. Sans lui, l'outil discute de la selection alors que le probleme est ailleurs.
VERDICT_AUCUN_GAGNANT = "AUCUNE_CONFIG_N_EST_PROFITABLE_MEME_EN_TRAIN"


# --------------------------------------------------------------------------- selections


def selection_par_maximum(scores: list[tuple[object, float]], k: int) -> list[object]:
    """Ce que fait le code aujourd'hui : les k meilleurs scores de TRAIN.

    Sur un tres grand nombre de candidats, c'est un tirage du MAXIMUM D'UN BRUIT.
    """
    ordonnes = sorted(scores, key=lambda x: float(x[1]), reverse=True)
    return [sc for sc, _s in ordonnes[: max(1, int(k))]]


def selection_par_plateau(
    scores: list[tuple[object, float]],
    k: int,
    *,
    vecteur,
    voisins: int = 12,
) -> list[object]:
    """On classe une config sur la MEDIANE de son voisinage, pas sur son propre score.

    `vecteur(sc) -> tuple[float, ...]` : les coordonnees NORMALISEES de la config.

    Un pic isole (chance) a des voisins mediocres -> mediane faible -> il ne remonte pas.
    Un vrai edge cree un PLATEAU -> ses voisins sont bons aussi -> il remonte.

    C'est plus lent (O(n^2) sur le nombre de configs retenues), donc a appliquer sur une
    PRE-SELECTION large (ex : les 5 000 meilleures du maximum), pas sur les 150 M brutes.
    Mais surtout : plus honnete.
    """
    if not scores:
        return []
    vecs = [(sc, vecteur(sc), float(s)) for sc, s in scores]
    robustes: list[tuple[object, float]] = []
    for sc, v, _s in vecs:
        d = sorted(
            ((math.dist(v, ov), os_) for _osc, ov, os_ in vecs if ov != v),
            key=lambda x: x[0],
        )[:voisins]
        nets = sorted(n for _dd, n in d)
        if not nets:
            robustes.append((sc, float("-inf")))
            continue
        med = nets[len(nets) // 2] if len(nets) % 2 else (nets[len(nets) // 2 - 1]
                                                          + nets[len(nets) // 2]) / 2.0
        robustes.append((sc, med))
    robustes.sort(key=lambda x: x[1], reverse=True)
    return [sc for sc, _m in robustes[: max(1, int(k))]]


# --------------------------------------------------------------------------- le controle


@dataclass(frozen=True, slots=True)
class BorneDuHasard:
    verdict: str
    max_reel: float
    max_hasard_moyen: float
    max_hasard_p95: float
    n_permutations: int
    n_scenarios: int
    ecart: float = 0.0                       # max_reel - p95 du hasard, en $ (SIGNE-SUR)
    ratio: float = 0.0                       # max_reel / p95, UNIQUEMENT si les deux sont > 0
    echantillon: tuple[float, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "max_reel": self.max_reel,
            "max_hasard_moyen": self.max_hasard_moyen,
            "max_hasard_p95": self.max_hasard_p95,
            "ecart_vs_p95": self.ecart,
            "ratio": self.ratio,
            "n_permutations": self.n_permutations,
            "n_scenarios": self.n_scenarios,
        }


def permuter_les_sens(candidats: list[dict], *, seed: int) -> list[dict]:
    """Detruit l'edge en RANDOMISANT le sens (LONG/SHORT), et RIEN d'autre.

    On garde : le coin, l'horodatage, le prix d'entree, l'age, le score, le consensus, la
    liquidite, la degradation. On ne touche QUE le lien signal -> direction.

    Si un edge existe, il vient de ce lien : le detruire doit faire s'effondrer le resultat.
    S'il ne s'effondre pas, c'est qu'il n'y avait pas d'edge -- juste du bruit bien classe.
    """
    rng = random.Random(seed)
    out = []
    for c in candidats:
        d = dict(c)
        d["direction"] = "LONG" if rng.random() < 0.5 else "SHORT"
        out.append(d)
    return out


def _pctl(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    i = min(len(ys) - 1, max(0, int(round(p / 100.0 * (len(ys) - 1)))))
    return ys[i]


def borne_du_hasard(
    *,
    max_reel: float,
    maxima_permutes: list[float],
    n_scenarios: int,
    marge_usd: float = 0.0,
) -> BorneDuHasard:
    """Le max du train REEL depasse-t-il ce que le HASARD produit sur le meme espace ?

    🔴 BUG CORRIGE LE 2026-07-13 -- ET C'EST MON PROPRE OUTIL QUI MENTAIT.
    -------------------------------------------------------------------
    L'ancienne version faisait :

        seuil = p95 * marge if p95 > 0 else 0.0        # <-- ICI
        verdict = SIGNAL if max_reel > seuil else BRUIT

    Quand le p95 du hasard est NEGATIF -- ce qui est le cas normal sur un marche ou le PnL
    moyen par trade est negatif -- le seuil s'effondre a **0**. Il faut alors que le max REEL
    soit **positif** pour esperer un verdict « signal ». Sur des donnees perdantes, le verdict
    etait donc *mecaniquement* « BRUIT », quoi qu'il arrive.

    Sur la vraie mesure : max_reel = **-106,46 $**, p95 du hasard = **-224,94 $**. Le reel est
    118 $ AU-DESSUS du hasard -- et l'outil imprimait « indiscernable du hasard ». Faux.

    On compare desormais **max_reel > p95**, tout simplement, quel que soit le SIGNE. La marge
    devient ADDITIVE (en $), parce qu'une marge multiplicative n'a aucun sens sur des negatifs
    (multiplier -225 par 1,5 le fait *descendre*, pas monter).

    Lecon (deja payee 3 fois) : *un outil de mesure qui se trompe est PIRE qu'une absence de
    mesure -- on lui fait confiance.*
    """
    if not maxima_permutes:
        return BorneDuHasard(VERDICT_INSUFFISANT, max_reel, 0.0, 0.0, 0, n_scenarios)

    moy = sum(maxima_permutes) / len(maxima_permutes)
    p95 = _pctl(maxima_permutes, 95.0)

    seuil = p95 + float(marge_usd)           # ADDITIF : sain quel que soit le signe
    ecart = max_reel - p95
    ratio = (max_reel / p95) if (p95 > 0 and max_reel > 0) else 0.0

    if max_reel <= 0.0:
        # 🔴 LE VERDICT QUI COMPTE VRAIMENT. Si meme le MEILLEUR scenario perd EN TRAIN, il n'y
        # a aucun vainqueur a maudire : le probleme n'est pas la PROCEDURE DE SELECTION, il est
        # dans les donnees. Corriger la selection ne creera pas un gagnant qui n'existe pas.
        verdict = VERDICT_AUCUN_GAGNANT
    elif max_reel > seuil:
        verdict = VERDICT_SIGNAL
    else:
        verdict = VERDICT_BRUIT

    return BorneDuHasard(
        verdict=verdict,
        max_reel=round(max_reel, 4),
        max_hasard_moyen=round(moy, 4),
        max_hasard_p95=round(p95, 4),
        n_permutations=len(maxima_permutes),
        n_scenarios=int(n_scenarios),
        ecart=round(ecart, 4),
        ratio=round(ratio, 4),
        echantillon=tuple(round(x, 3) for x in sorted(maxima_permutes)[:10]),
    )


def compare_leaders_to_activity_placebos(
    leaders: Sequence[Mapping[str, Any]],
    placebo_wallets: Sequence[Mapping[str, Any]],
    *,
    cohort_field: str = "cohort_id",
    activity_field: str = "activity_count",
    net_field: str = "net_usd",
    cost_field: str = "cost_usd",
    identity_field: str = "wallet_id",
    seed: int = 7,
) -> dict[str, Any]:
    """Compare leaders with distinct placebo wallets in the same cohort and cost bucket.

    A placebo is eligible only when its temporal cohort, activity count and exact
    observed cost match the leader. Matching is without replacement and deterministic
    under ``seed``; duplicate identities, missing values or an under-sized placebo
    bucket fail closed. The result is a PAPER/read-only comparison and never a claim
    of economic causality.
    """
    base: dict[str, Any] = {
        "status": "UNMEASURABLE",
        "verdict": "INSUFFICIENT_DATA",
        "reason": None,
        "n_leaders": len(leaders or []),
        "n_placebos": len(placebo_wallets or []),
        "n_pairs": 0,
        "leader_mean_net_usd": None,
        "placebo_mean_net_usd": None,
        "delta_mean_net_usd": None,
        "paired_differences_usd": [],
        "missing_match_groups": [],
        "same_cohort": True,
        "same_activity": True,
        "same_costs": True,
        "selection": "seeded_without_replacement",
        "real_execution": False,
    }
    if not isinstance(seed, int) or isinstance(seed, bool):
        base["reason"] = "seed_invalide"
        return base
    if not leaders or not placebo_wallets:
        base["reason"] = "leaders_ou_placebos_absents"
        return base

    fields = (cohort_field, activity_field, net_field, cost_field, identity_field)

    def normalize(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping) or any(field not in row for field in fields):
                return [], "champ_manquant"
            identity = row[identity_field]
            cohort = row[cohort_field]
            activity = row[activity_field]
            net = row[net_field]
            cost = row[cost_field]
            if identity is None or cohort is None or isinstance(activity, bool) or not isinstance(activity, int) or activity < 1:
                return [], "identifiant_ou_activite_invalide"
            if isinstance(identity, (list, dict, set)) or isinstance(cohort, (list, dict, set)):
                return [], "identifiant_ou_cohorte_invalide"
            identity_key = str(identity)
            if not identity_key or identity_key in seen:
                return [], "identite_dupliquee"
            seen.add(identity_key)
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
                   for value in (net, cost)) or float(cost) < 0.0:
                return [], "net_ou_cout_invalide"
            normalized.append({
                "identity": identity_key,
                "cohort": cohort,
                "activity": activity,
                "net": float(net),
                "cost": float(cost),
            })
        return normalized, None

    leader_rows, error = normalize(leaders)
    if error:
        base["reason"] = f"leaders:{error}"
        return base
    placebo_rows, error = normalize(placebo_wallets)
    if error:
        base["reason"] = f"placebos:{error}"
        return base
    leaders_ids = {row["identity"] for row in leader_rows}
    buckets: dict[tuple[Any, int, float], list[dict[str, Any]]] = {}
    for row in placebo_rows:
        if row["identity"] not in leaders_ids:
            buckets.setdefault((row["cohort"], row["activity"], row["cost"]), []).append(row)

    rng = random.Random(seed)
    differences: list[float] = []
    missing: list[dict[str, Any]] = []
    used: set[str] = set()
    for leader in leader_rows:
        key = (leader["cohort"], leader["activity"], leader["cost"])
        candidates = [row for row in buckets.get(key, []) if row["identity"] not in used]
        if not candidates:
            missing.append({"cohort": leader["cohort"], "activity": leader["activity"], "cost": leader["cost"]})
            continue
        chosen = rng.choice(candidates)
        used.add(chosen["identity"])
        differences.append(leader["net"] - chosen["net"])

    base["n_pairs"] = len(differences)
    base["paired_differences_usd"] = [round(value, 12) for value in differences]
    base["missing_match_groups"] = missing
    if missing or len(differences) < 2:
        base["reason"] = "placebo_apparie_insuffisant"
        return base
    leader_nets = [row["net"] for row in leader_rows]
    selected_placebo_nets = [leader["net"] - delta for leader, delta in zip(leader_rows, differences, strict=False)]
    base.update(
        status="PROVEN",
        verdict="MESURE_PLACEBO_APPARIEE",
        leader_mean_net_usd=statistics.fmean(leader_nets),
        placebo_mean_net_usd=statistics.fmean(selected_placebo_nets),
        delta_mean_net_usd=statistics.fmean(differences),
    )
    return base


def comparer_leaders_placebos_activite(leaders: Sequence[Mapping[str, Any]], placebo_wallets: Sequence[Mapping[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """French alias for ``compare_leaders_to_activity_placebos``."""
    return compare_leaders_to_activity_placebos(leaders, placebo_wallets, **kwargs)


__all__ = [
    "SELECTION_MAX", "SELECTION_PLATEAU",
    "VERDICT_BRUIT", "VERDICT_SIGNAL", "VERDICT_INSUFFISANT",
    "BorneDuHasard",
    "selection_par_maximum", "selection_par_plateau",
    "permuter_les_sens", "borne_du_hasard",
    "compare_leaders_to_activity_placebos", "comparer_leaders_placebos_activite",
]
