"""LE MODÈLE NE PEUT PAS ÊTRE PROMU S'IL PERD CONTRE LA BASELINE (2026-07-11).

CE QUE LA MESURE DIT AUJOURD'HUI :

    exemples          : 77  (14 gains / 63 pertes)   <- deja tres desequilibre
    evalue sur        : 24 exemples
    Brier du modele   : 0,134709
    Brier de baseline : 0,109375
    beats_baseline    : FALSE

**Le modele fait MOINS BIEN que de predire simplement le taux de base.** Un modele qui perd contre
la baseline n'est pas "presque pret" : il est PIRE que rien. Et une accuracy flatteuse sur une
classe ecrasee (63 pertes contre 14 gains) ne prouve rien du tout -- il suffit de tout predire
"perte" pour avoir 82 % d'accuracy et zero valeur.

CE QUI EXISTAIT DEJA, ET QUI EST BIEN : `apply_model_promotion` ne peut que DURCIR (transformer un
ACCEPT en refus), jamais CREER un trade. Le risque etait donc borne.

CE QUI MANQUAIT, ET QUE CE MODULE POSE : **rien ne verifiait que le modele bat la baseline avant de
le passer en mode autoritaire.** Le flag suffisait. Un modele perdant pouvait donc se mettre a
refuser des trades sur la foi d'une probabilite qui ne vaut rien -- pas dangereux pour le capital,
mais malhonnete : on aurait attribue a "l'IA" des refus qui ne sont que du bruit.

Desormais la promotion exige, TOUTES conditions reunies :
  * `beats_baseline` VRAI (Brier strictement inferieur a la baseline) ;
  * un avantage NON MARGINAL (au-dela du bruit d'echantillonnage) ;
  * assez d'exemples d'evaluation ;
  * assez d'exemples de la classe MINORITAIRE (sinon on n'a rien appris du cas rare).

**Deny-by-default** : metriques absentes ou illisibles => PAS de promotion.

Aucun ordre reel. Pur, sans I/O reseau.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

# Ces seuils ne sont pas de la prudence decorative : sous ces valeurs, "battre la baseline"
# n'est pas distinguable du hasard.
MIN_EVAL_SAMPLES = 200          # 24 exemples ne prouvent rien
MIN_MINORITY_SAMPLES = 50       # sans cas rares, le modele n'a pas vu ce qu'il doit predire
MIN_BRIER_ADVANTAGE = 0.005     # un avantage plus petit est du bruit

ENV_ALLOW_PROMOTION = "HYPERSMART_V13_MODEL_AUTHORITATIVE"


@dataclass(frozen=True, slots=True)
class PromotionVerdict:
    allowed: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"promotion_allowed": self.allowed, "reasons": list(self.reasons)}


def evaluate_promotion(metrics: Mapping[str, Any] | None) -> PromotionVerdict:
    """Le modele a-t-il le droit d'etre autoritaire ? DENY-BY-DEFAULT."""
    if not isinstance(metrics, Mapping) or metrics.get("empty") is True:
        return PromotionVerdict(False, ("NO_EVALUATION_METRICS",))

    raisons: list[str] = []

    if not bool(metrics.get("beats_baseline")):
        raisons.append("DOES_NOT_BEAT_BASELINE")

    try:
        avantage = float(metrics.get("brier_advantage") or 0.0)
    except (TypeError, ValueError):
        avantage = 0.0
    if avantage < MIN_BRIER_ADVANTAGE:
        raisons.append("BRIER_ADVANTAGE_WITHIN_NOISE")

    try:
        n = int(metrics.get("n") or 0)
    except (TypeError, ValueError):
        n = 0
    if n < MIN_EVAL_SAMPLES:
        raisons.append("EVAL_SAMPLE_TOO_SMALL")

    # la classe MINORITAIRE est celle qu'on veut vraiment predire. Sans elle, tout modele
    # "reussit" en predisant toujours la classe majoritaire -- et n'apprend rien.
    minoritaire = metrics.get("minority_samples")
    if minoritaire is not None:
        try:
            if int(minoritaire) < MIN_MINORITY_SAMPLES:
                raisons.append("MINORITY_CLASS_TOO_RARE")
        except (TypeError, ValueError):
            raisons.append("MINORITY_CLASS_UNKNOWN")

    return PromotionVerdict(not raisons, tuple(raisons))


def promotion_allowed(metrics: Mapping[str, Any] | None) -> bool:
    return evaluate_promotion(metrics).allowed


def authoritative_enabled(metrics: Mapping[str, Any] | None) -> bool:
    """Le mode autoritaire exige LE FLAG **ET** un modele qui a fait ses preuves.

    Le flag seul ne suffit plus : c'etait exactement le trou. Un modele qui perd contre la
    baseline ne doit pas pouvoir refuser des trades au nom de "l'IA" -- ce ne seraient que des
    refus aleatoires portant un nom prestigieux.
    """
    flag = str(os.environ.get(ENV_ALLOW_PROMOTION, "0")).strip().lower() in {"1", "true", "yes", "on"}
    return bool(flag) and promotion_allowed(metrics)


__all__ = [
    "ENV_ALLOW_PROMOTION",
    "MIN_BRIER_ADVANTAGE",
    "MIN_EVAL_SAMPLES",
    "MIN_MINORITY_SAMPLES",
    "PromotionVerdict",
    "authoritative_enabled",
    "evaluate_promotion",
    "promotion_allowed",
]
