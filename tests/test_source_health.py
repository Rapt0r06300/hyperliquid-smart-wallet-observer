"""LE FAUX « OK » (2026-07-11) — Phase 12 du brief.

LE BUG : `check_realtime_health` juge la santé sur **l'âge du fichier de log**. Des logs qui
s'écrivent → statut `LIVE_FROM_LOCAL_LOGS`. Même si ces logs ne contiennent **que des refus et
zéro signal frais**.

Le système se déclarait en bonne santé parce qu'il **écrivait**, pas parce qu'il **servait**.
C'est le même mensonge que « contrôles réussis » avec toutes les preuves à `null` : une apparence
de fonctionnement qui empêche de voir que rien ne fonctionne.

LA DISTINCTION QUI MANQUAIT :

    HEALTHY          → la source va bien ET produit des signaux frais
    NO_FRESH_SIGNAL  → la source va techniquement bien... et ne produit RIEN d'exploitable

**Ce ne sont pas le même état.** Les confondre laisse un bot tourner des heures en croyant qu'il
travaille.

Aucun ordre réel.
"""
from __future__ import annotations

from hl_observer.realtime.source_health import (
    BACKPRESSURED,
    CRITICAL,
    DATA_INCOMPLETE,
    GAP_DETECTED,
    HEALTHY,
    NO_FRESH_SIGNAL,
    RECONNECTING,
    STALE,
    evaluer_sante,
)


def _saine(**surcharges):
    base = dict(
        fresh_entry_deltas=5, fresh_follow_signals=2,
        market_data_age_ms=500.0, reconnects_recents=0, gaps_detectes=0,
        queue_lag_ms=10.0, events_dropped=0, contrat_incomplet=0,
        horloge_fiable=True, source_principale_active=True,
    )
    base.update(surcharges)
    return evaluer_sante(**base)


# ------------------------------------------------------------------ LE bug

def test_a_source_with_ZERO_fresh_signals_is_NOT_healthy():
    """LE CŒUR. Tout va techniquement bien — et il ne se passe RIEN. Ce n'est pas « OK »."""
    h = _saine(fresh_entry_deltas=0, fresh_follow_signals=0)
    assert h.status == NO_FRESH_SIGNAL
    assert h.status != HEALTHY
    assert "ZERO_SIGNAL_FRAIS" in h.reasons


def test_technically_fine_and_useful_are_TWO_different_questions():
    """La séparation qui manquait. Le dashboard doit montrer les DEUX, jamais un seul chiffre."""
    h = _saine(fresh_entry_deltas=0, fresh_follow_signals=0)
    assert h.techniquement_sain is True          # la source va bien...
    assert h.produit_des_signaux_frais is False  # ...et ne sert à rien
    assert h.utilisable is False, "une source qui ne produit rien est déclarée utilisable"

    d = h.as_dict()
    assert d["techniquement_sain"] is True and d["produit_des_signaux_frais"] is False


def test_a_genuinely_healthy_source_is_recognised():
    """Symétrie de l'honnêteté : on ne crie pas au loup sur une source qui va vraiment bien."""
    h = _saine()
    assert h.status == HEALTHY
    assert h.utilisable is True
    assert h.reasons == ()


# ------------------------------------------------------------------ chaque panne a son nom

def test_stale_market_data_is_named():
    h = _saine(market_data_age_ms=60_000.0)
    assert h.status == STALE
    assert h.techniquement_sain is False


def test_a_gap_is_named():
    h = _saine(gaps_detectes=3)
    assert h.status == GAP_DETECTED


def test_dropped_events_mean_backpressure():
    """Un événement perdu en silence est un signal qu'on ne verra JAMAIS. Ça doit se voir."""
    h = _saine(events_dropped=1)
    assert h.status == BACKPRESSURED
    assert any("PERDUS" in r for r in h.reasons)


def test_a_late_queue_means_backpressure():
    h = _saine(queue_lag_ms=30_000.0)
    assert h.status == BACKPRESSURED


def test_reconnecting_is_named():
    h = _saine(reconnects_recents=2)
    assert h.status == RECONNECTING


def test_an_incomplete_contract_is_named():
    h = _saine(contrat_incomplet=4)
    assert h.status == DATA_INCOMPLETE


def test_an_unknown_market_data_age_is_INCOMPLETE_not_fine():
    """Ne pas connaître l'âge de la donnée n'est PAS rassurant. C'est une donnée manquante."""
    h = _saine(market_data_age_ms=None)
    assert h.status == DATA_INCOMPLETE
    assert "AGE_DONNEE_MARCHE_INCONNU" in h.reasons


# ------------------------------------------------------------------ les cas critiques

def test_an_unreliable_clock_is_CRITICAL():
    """Sans horloge fiable, TOUTE mesure de fraîcheur est fausse — y compris celles qui rassurent."""
    h = _saine(horloge_fiable=False)
    assert h.status == CRITICAL


def test_a_dead_primary_source_is_CRITICAL():
    h = _saine(source_principale_active=False)
    assert h.status == CRITICAL


def test_the_WORST_state_wins_never_an_average():
    """Un système malade de trois maux ne va pas « moyennement » bien : il va aussi mal que son
    pire mal. Une moyenne masquerait le plus grave."""
    h = _saine(reconnects_recents=1, gaps_detectes=1, source_principale_active=False)
    assert h.status == CRITICAL
    assert len(h.reasons) >= 3, "les autres problèmes ont disparu du rapport"


def test_a_broken_source_with_signals_is_still_broken():
    """Des signaux frais ne rachètent PAS une source qui perd des événements."""
    h = _saine(fresh_entry_deltas=10, events_dropped=5)
    assert h.status == BACKPRESSURED
    assert h.utilisable is False
