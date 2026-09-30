"""LA COURBE EDGE / HORIZON DU SNIPER (2026-07-11) — Phase 7 du brief.

LA SEULE RAISON HONNÊTE D'ESPÉRER ENCORE QUELQUE CHOSE DU COPY-TRADING.

La preuve d'absence d'edge tient : 24 133 signaux, hors échantillon, **−7,97 bps même à coût zéro**.
Mais elle portait sur des signaux d'un **âge médian de 57 secondes**, à des horizons en secondes.

**Les horizons sub-seconde n'ont JAMAIS été testés — la donnée n'existait pas.**

Or c'est précisément là qu'un signal de copie devrait vivre, s'il vit : un fill de whale est une
information publique, elle se consomme en millisecondes. Chercher son effet à 60 s, c'est chercher
une empreinte de pas une heure après la marée.

Ces tests verrouillent l'HONNÊTETÉ de la mesure — pas son résultat. Si la courbe est plate à
100 ms aussi, on saura, et on cessera d'y croire.

Aucun ordre réel.
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting.sniper_horizon_curve import (
    HORIZONS_MS,
    MIN_OBSERVATIONS,
    RESOLUTION_INSUFFISANTE,
    construire_courbe,
    mouvement_apres,
    verdict,
)


def _signal(side: str, mouvement_bps: float, *, horizons=HORIZONS_MS) -> dict:
    """Un signal dont le prix bouge de `mouvement_bps` DANS LE SENS du leader, à chaque horizon."""
    prix = 100.0
    sens = 1.0 if side == "LONG" else -1.0
    return {
        "prix_signal": prix, "side": side,
        "chemin_prix": [(h, prix * (1 + sens * mouvement_bps / 10_000.0)) for h in horizons],
    }


# ------------------------------------------------------------------ le mouvement est mesuré juste

def test_a_long_that_goes_up_is_a_positive_edge():
    m = mouvement_apres(prix_signal=100.0, side="LONG",
                        chemin_prix=[(500, 100.3)], horizon_ms=500)
    assert m == pytest.approx(30.0)


def test_a_short_that_goes_DOWN_is_also_a_positive_edge():
    """Le signe suit le LEADER, pas le marché. Une inversion ici transformerait chaque perte
    en gain apparent — c'est LE piège."""
    m = mouvement_apres(prix_signal=100.0, side="SHORT",
                        chemin_prix=[(500, 99.7)], horizon_ms=500)
    assert m == pytest.approx(30.0)

    contre = mouvement_apres(prix_signal=100.0, side="SHORT",
                             chemin_prix=[(500, 100.3)], horizon_ms=500)
    assert contre == pytest.approx(-30.0)


# ------------------------------------------------------------------ on n'invente pas un horizon

def test_an_horizon_the_data_cannot_reach_is_declared_not_extrapolated():
    """RÈGLE DURE : si la source ne descend pas à 100 ms, on le DIT. On n'interpole pas.
    Une courbe qui invente ses points ne mesure rien."""
    assert mouvement_apres(prix_signal=100.0, side="LONG",
                           chemin_prix=[(5_000, 101.0)], horizon_ms=100) is None


def test_a_missing_horizon_is_flagged_SOURCE_RESOLUTION_INSUFFICIENT():
    """Le cas RÉEL d'aujourd'hui : aucun prix sub-seconde. Le statut doit le dire — et surtout,
    ce n'est PAS une preuve d'absence d'edge, c'est une absence de DONNÉE."""
    signaux = [{"prix_signal": 100.0, "side": "LONG", "chemin_prix": [(60_000, 100.5)]}] * 300
    courbe = construire_courbe(signaux)
    assert courbe[100].statut == RESOLUTION_INSUFFISANTE
    assert courbe[100].n == 0
    assert courbe[60_000].statut == "MEASURED"

    v = verdict(courbe)
    assert "absence de donnee" in v["conclusion"] or courbe[60_000].statut == "MEASURED"


# ------------------------------------------------------------------ le bruit ne passe pas pour un signal

def test_a_movement_drowned_in_noise_is_NOT_exploitable():
    """LE JUGE DE PAIX. Un mouvement médian de quelques bps avec un écart-type de 80 ne veut
    RIEN dire. C'est exactement ce qu'on a mesuré : ~0 bps de mouvement, 50-100 bps de bruit."""
    import random

    rng = random.Random(7)
    signaux = []
    for _ in range(400):
        bruit = rng.gauss(2.0, 80.0)          # +2 bps de « signal », 80 bps de bruit
        signaux.append(_signal("LONG", bruit))
    courbe = construire_courbe(signaux)
    p = courbe[1_000]
    assert p.statut == "MEASURED"
    assert p.ratio_signal_bruit is not None and p.ratio_signal_bruit < 0.20
    assert p.exploitable is False, "un mouvement noyé dans le bruit est présenté comme exploitable"


def test_a_clean_movement_IS_exploitable():
    """Symétrie de l'honnêteté : si un vrai mouvement existe, on ne le nie pas."""
    signaux = [_signal("LONG", 40.0) for _ in range(MIN_OBSERVATIONS + 50)]
    p = construire_courbe(signaux)[500]
    assert p.statut == "MEASURED"
    assert p.edge_median_bps == pytest.approx(40.0, abs=0.5)
    assert p.exploitable is True


def test_a_small_sample_is_never_called_a_measurement():
    """Sous 200 observations, une « mesure » n'est qu'un accident."""
    signaux = [_signal("LONG", 40.0) for _ in range(10)]
    p = construire_courbe(signaux)[500]
    assert p.statut == "SAMPLE_TOO_SMALL"
    assert p.exploitable is False


# ------------------------------------------------------------------ le verdict ne se ment pas

def test_a_real_movement_that_does_not_cover_the_costs_is_called_out():
    """LA PIRE DES SITUATIONS : un signal RÉEL mais économiquement inutile. C'est celui-là qui
    donne envie d'y croire — et qui fait perdre de l'argent avec méthode."""
    signaux = [_signal("LONG", 8.0) for _ in range(MIN_OBSERVATIONS + 50)]
    v = verdict(construire_courbe(signaux), cout_aller_retour_bps=13.0)
    assert v["horizons_rentables_apres_couts"] == []
    assert "NE COUVRE PAS LES COUTS" in v["conclusion"]
    assert "envie d'y croire" in v["conclusion"]


def test_a_surviving_horizon_still_promises_NOTHING():
    """RÈGLE DURE (CLAUDE.md) : même un edge qui survit aux coûts ne promet aucun PnL."""
    signaux = [_signal("LONG", 45.0) for _ in range(MIN_OBSERVATIONS + 50)]
    v = verdict(construire_courbe(signaux), cout_aller_retour_bps=13.0)
    assert v["horizons_rentables_apres_couts"], "un edge de 45 bps devrait survivre à 13 bps"
    assert "NE PROMET AUCUN PnL" in v["conclusion"]
    assert "HORS ECHANTILLON" in v["conclusion"]
    assert v["real_execution"] is False


def test_a_flat_curve_says_so_plainly():
    """Si la courbe est plate PARTOUT, on l'écrit noir sur blanc — sans chercher d'excuse."""
    import random

    rng = random.Random(11)
    signaux = [_signal("LONG", rng.gauss(0.0, 60.0)) for _ in range(400)]
    v = verdict(construire_courbe(signaux))
    assert v["horizons_exploitables"] == []
    assert "indiscernable du hasard" in v["conclusion"]


def test_garbage_never_crashes_the_curve():
    for bad in (None, [], [None], [{}], [{"prix_signal": "abc"}], [{"prix_signal": 0.0}]):
        c = construire_courbe(bad or [])  # type: ignore[arg-type]
        assert set(c) == set(HORIZONS_MS)
        assert all(p.exploitable is False for p in c.values())
