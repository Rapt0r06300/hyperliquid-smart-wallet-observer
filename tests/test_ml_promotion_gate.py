"""LE MODÈLE QUI PERD CONTRE LA BASELINE NE PEUT PAS ÊTRE PROMU (2026-07-11) — P13.

Chiffres RÉELS du rapport IA actuel :

    77 exemples (14 gains / 63 pertes) · évalué sur 24 · Brier 0,134709 · baseline 0,109375
    → beats_baseline = FALSE

**Le modèle fait moins bien que de prédire bêtement le taux de base.** Il n'est pas « presque
prêt » : il est **pire que rien**.

Ce qui existait déjà et qui est bon : la promotion ne peut que DURCIR (transformer un ACCEPT en
refus), jamais créer un trade. Le capital n'était pas en danger.

Ce qui manquait : **rien ne vérifiait qu'il bat la baseline avant de l'activer.** Le flag suffisait.
Un modèle perdant aurait pu refuser des trades au nom de « l'IA » — des refus aléatoires portant un
nom prestigieux. C'est de la malhonnêteté, même sans perte d'argent.

Aucun ordre réel.
"""
from __future__ import annotations

from hl_observer.ml.promotion_gate import (
    MIN_BRIER_ADVANTAGE,
    MIN_EVAL_SAMPLES,
    MIN_MINORITY_SAMPLES,
    authoritative_enabled,
    evaluate_promotion,
    promotion_allowed,
)

# Les métriques RÉELLES, telles que mesurées aujourd'hui.
MODELE_ACTUEL = {
    "n": 24, "brier": 0.134709, "baseline_brier": 0.109375,
    "brier_advantage": -0.025334, "accuracy": 0.7917,
    "beats_baseline": False, "empty": False, "minority_samples": 14,
}


def test_the_current_model_is_REFUSED_promotion():
    """LE TEST QUI COMPTE. Le modèle d'aujourd'hui ne doit PAS pouvoir devenir autoritaire."""
    v = evaluate_promotion(MODELE_ACTUEL)
    assert v.allowed is False
    assert "DOES_NOT_BEAT_BASELINE" in v.reasons


def test_it_is_refused_for_SEVERAL_reasons_not_just_one():
    """Il échoue sur plusieurs fronts à la fois : c'est un modèle non entraîné, pas un modèle
    qui rate de peu."""
    v = evaluate_promotion(MODELE_ACTUEL)
    assert "EVAL_SAMPLE_TOO_SMALL" in v.reasons        # 24 << 200
    assert "BRIER_ADVANTAGE_WITHIN_NOISE" in v.reasons  # avantage NÉGATIF
    assert "MINORITY_CLASS_TOO_RARE" in v.reasons       # 14 gains << 50


def test_the_flag_alone_is_no_longer_enough(monkeypatch):
    """LE TROU QU'ON FERME : avant, le flag suffisait. Un modèle perdant pouvait être activé."""
    monkeypatch.setenv("HYPERSMART_V13_MODEL_AUTHORITATIVE", "1")
    assert authoritative_enabled(MODELE_ACTUEL) is False, (
        "le flag seul active un modèle qui perd contre la baseline"
    )


# ---------------------------------------------------------------- deny-by-default

def test_absent_metrics_mean_no_promotion():
    """Pas de mesure = pas de promotion. On n'accorde pas le bénéfice du doute à un modèle."""
    for absent in (None, {}, {"empty": True}, "pas un dict"):
        assert promotion_allowed(absent) is False  # type: ignore[arg-type]


def test_corrupt_metrics_never_authorise():
    assert promotion_allowed({"beats_baseline": True, "brier_advantage": "abc", "n": "xyz"}) is False


def test_the_flag_is_off_by_default():
    """Même un modèle EXCELLENT reste en shadow tant que le flag n'est pas posé explicitement."""
    excellent = {"n": 5_000, "brier_advantage": 0.05, "beats_baseline": True,
                 "minority_samples": 800, "empty": False}
    assert promotion_allowed(excellent) is True          # il MÉRITE la promotion...
    assert authoritative_enabled(excellent) is False     # ...mais il faut encore l'ACTIVER


# ---------------------------------------------------------------- un bon modèle peut passer

def test_a_genuinely_good_model_can_be_promoted(monkeypatch):
    """Symétrie de l'honnêteté : le gate ne bloque pas tout — il bloque le NON PROUVÉ."""
    monkeypatch.setenv("HYPERSMART_V13_MODEL_AUTHORITATIVE", "1")
    bon = {"n": MIN_EVAL_SAMPLES, "brier_advantage": MIN_BRIER_ADVANTAGE,
           "beats_baseline": True, "minority_samples": MIN_MINORITY_SAMPLES, "empty": False}
    assert evaluate_promotion(bon).allowed is True
    assert authoritative_enabled(bon) is True


def test_a_marginal_advantage_is_treated_as_noise():
    """Battre la baseline de 0,0001 n'est pas battre la baseline : c'est du hasard."""
    marginal = {"n": 5_000, "brier_advantage": 0.0001, "beats_baseline": True,
                "minority_samples": 800, "empty": False}
    v = evaluate_promotion(marginal)
    assert v.allowed is False
    assert "BRIER_ADVANTAGE_WITHIN_NOISE" in v.reasons


def test_a_high_accuracy_on_an_imbalanced_class_is_not_enough():
    """79 % d'accuracy sur 63 pertes / 14 gains : il suffit de tout prédire « perte ».
    L'accuracy ne doit JAMAIS suffire à promouvoir."""
    trompeur = {"n": 5_000, "accuracy": 0.95, "beats_baseline": False,
                "brier_advantage": -0.01, "minority_samples": 800, "empty": False}
    assert promotion_allowed(trompeur) is False
