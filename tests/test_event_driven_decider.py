"""DÉCIDER À L'ARRIVÉE DU FILL, PAS À LA FIN DU CYCLE (2026-07-11) — Phase 4 + 15.

LE PROBLÈME, MESURÉ SUR TES LOGS :

    cycle de poll médian **30,6 s** | p95 **50,4 s** | max **106,1 s**

Le firehose WebSocket stocke chaque fill de leader en **sub-seconde**. Puis le signal **attend
30 secondes** qu'on daigne le regarder. **Le hot path est prisonnier du cold path.**

Aucun réglage de seuil ne corrige ça : le signal est déjà mort quand on l'examine.

MODE SHADOW — ET CE N'EST PAS DE LA TIMIDITÉ. Ce décideur n'ouvre **rien**. Il observe les mêmes
événements, décide immédiatement, et enregistre ce qu'il **aurait** fait. Changer le pipeline ET le
comportement en même temps rendrait impossible de savoir lequel des deux a changé le résultat.

Aucun ordre réel.
"""
from __future__ import annotations

import time

from hl_observer.runtime.bounded_event_queue import Event
from hl_observer.runtime.event_driven_decider import (
    ENV_AUTORITAIRE,
    EventDrivenDecider,
    comparer,
)

T0 = 1_800_000_000_000


def _preuve_complete(event: Event) -> dict:
    """Une preuve qui remplit le contrat (Phase 6) — le nouveau chemin n'est pas plus laxiste."""
    return {
        "strategy_mode": "SNIPER", "strategy_id": "copy_event_driven",
        "signal_id": event.event_id, "source_type": event.event_type,
        "source_event_time_ms": event.event_time_ms,
        "local_receive_time_ms": event.event_time_ms + 200,
        "signal_age_ms": 200,
        "coin": event.payload.get("coin", "BTC"), "side": event.payload.get("side", "LONG"),
        "current_mid": 100.0, "spread_bps": 1.2, "slippage_estimate_bps": 2.0, "fees_bps": 4.5,
        "liquidity_score": 0.9,
        "gross_expected_edge_bps": 30.0, "edge_remaining_bps": 22.0,
        "edge_is_empirical": True,
        "data_quality_status": "LIVE_BOOK", "decision": "PENDING", "reason_codes": [],
    }


def _preuve_trouee(event: Event) -> dict:
    p = _preuve_complete(event)
    p["signal_age_ms"] = None          # exactement le trou du ledger réel
    return p


def _fill(i: int, *, side: str = "LONG") -> Event:
    return Event(event_id=f"fill-{i}", event_type="userFill",
                 event_time_ms=int(time.time() * 1000),
                 payload={"coin": "BTC", "side": side})


# ------------------------------------------------------------------ LE point du brief

def test_a_fill_is_decided_IMMEDIATELY_not_at_the_end_of_a_30s_cycle():
    """LE CŒUR. Le signal arrive → la décision tombe. Pas dans 30 secondes."""
    d = EventDrivenDecider(construire_preuve=_preuve_complete)
    decision = d.on_event(_fill(1))

    assert decision is not None
    assert decision.decision == "ACCEPT_SHADOW"
    # le traitement LOCAL se compte en millisecondes, pas en dizaines de secondes
    assert decision.local_processing_ms is not None
    assert decision.local_processing_ms < 50, (
        f"la décision a pris {decision.local_processing_ms} ms : le hot path est encore bloqué"
    )


def test_the_two_clocks_stay_separate_in_the_decision():
    """Âge source (horloge murale) et traitement local (horloge MONOTONE) : jamais additionnés."""
    d = EventDrivenDecider(construire_preuve=_preuve_complete)
    dec = d.on_event(_fill(1))
    out = dec.as_dict()
    assert "source_age_ms" in out and "local_processing_ms" in out
    assert "total_ms" not in out


def test_every_stage_of_the_hot_path_is_timed():
    d = EventDrivenDecider(construire_preuve=_preuve_complete)
    dec = d.on_event(_fill(1))
    etapes = dec.stage_durations_ms
    assert any("gates" in k for k in etapes)
    assert any("decision" in k for k in etapes)


# ------------------------------------------------------------------ il n'est PAS plus laxiste

def test_the_new_path_uses_the_SAME_data_contract():
    """Un nouveau chemin plus rapide ET plus laxiste, ce serait tricher : il paraîtrait meilleur
    en acceptant ce que l'ancien refusait à raison."""
    d = EventDrivenDecider(construire_preuve=_preuve_trouee)
    dec = d.on_event(_fill(1))
    assert dec.decision == "NO_TRADE"
    assert any("MISSING_SIGNAL_AGE_MS" in r or "NO_TRADE_DATA_GAP" in r for r in dec.reason_codes)


def test_a_fabricated_edge_is_refused_here_too():
    def preuve_edge_faux(e: Event) -> dict:
        p = _preuve_complete(e)
        p["edge_is_empirical"] = False
        return p

    d = EventDrivenDecider(construire_preuve=preuve_edge_faux)
    dec = d.on_event(_fill(1))
    assert dec.decision == "NO_TRADE"
    assert "EDGE_NOT_EMPIRICAL" in dec.reason_codes


# ------------------------------------------------------------------ ce qui déclenche, et ce qui non

def test_a_price_snapshot_does_NOT_trigger_a_decision():
    """Un prix met à jour l'état ; il ne DÉCIDE rien. Confondre les deux, c'est re-décider
    mille fois par seconde pour rien."""
    d = EventDrivenDecider(construire_preuve=_preuve_complete)
    assert d.on_event(Event("m1", "allMids", T0, payload={"coin": "BTC"}, coalesce_key="BTC")) is None
    assert d.stats.decisions == 0
    assert d.stats.ignores_non_declencheurs == 1


def test_a_duplicate_fill_is_not_decided_twice():
    """Après une reconnexion, le WS renvoie un snapshot. Le rejouer fabriquerait des signaux
    qui n'ont jamais eu lieu."""
    d = EventDrivenDecider(construire_preuve=_preuve_complete)
    e = _fill(1)
    assert d.on_event(e) is not None
    assert d.on_event(e) is None
    assert d.stats.decisions == 1


# ------------------------------------------------------------------ SHADOW : il n'ouvre RIEN

def test_the_shadow_decider_NEVER_executes():
    d = EventDrivenDecider(construire_preuve=_preuve_complete)
    for dec in d.run([_fill(i) for i in range(5)]):
        assert dec.real_execution is False
        assert dec.as_dict()["shadow_only"] is True


def test_it_is_OFF_by_default(monkeypatch):
    monkeypatch.delenv("HYPERSMART_EVENT_DRIVEN_DECIDER", raising=False)
    assert EventDrivenDecider.actif() is False
    assert EventDrivenDecider.autoritaire() is False


def test_the_flag_alone_does_NOT_make_it_authoritative(monkeypatch):
    """RÈGLE DURE : un décideur jamais comparé à l'ancien n'a AUCUN droit d'ouvrir une position,
    aussi élégant soit son code."""
    monkeypatch.setenv("HYPERSMART_EVENT_DRIVEN_DECIDER", "1")
    monkeypatch.delenv(ENV_AUTORITAIRE, raising=False)
    assert EventDrivenDecider.actif() is True
    assert EventDrivenDecider.autoritaire() is False


# ------------------------------------------------------------------ la comparaison A/B

def test_the_comparison_shows_the_freshness_gain():
    """ANCIEN : signal vu à 30 000 ms. NOUVEAU : vu à 200 ms. C'est CE chiffre qu'on veut."""
    d = EventDrivenDecider(construire_preuve=_preuve_complete)
    nouveau = d.run([_fill(i) for i in range(3)])
    ancien = [{"event_id": f"fill-{i}", "decision": "ACCEPT", "signal_age_ms": 30_000}
              for i in range(3)]

    r = comparer(ancien, nouveau)
    assert r["evenements_communs"] == 3
    assert r["gain_fraicheur_median_ms"] is not None
    assert r["gain_fraicheur_median_ms"] > 25_000, "le gain de fraîcheur n'apparaît pas"


def test_the_comparison_names_the_divergences():
    """Là où les deux chemins décident différemment, on veut savoir POURQUOI."""
    d = EventDrivenDecider(construire_preuve=_preuve_trouee)     # le nouveau refuse
    nouveau = d.run([_fill(1)])
    ancien = [{"event_id": "fill-1", "decision": "ACCEPT", "signal_age_ms": 30_000}]

    r = comparer(ancien, nouveau)
    assert r["divergences"] == 1
    assert r["taux_divergence"] == 1.0
    assert "NO_TRADE" in r["lignes"][0]["divergence_reason"]


def test_the_comparison_refuses_to_call_FASTER_a_win():
    """RÈGLE DURE. Un chemin qui décide plus vite sur un signal SANS EDGE décide juste plus vite
    de perdre de l'argent. Le gain technique n'est pas un gain économique."""
    d = EventDrivenDecider(construire_preuve=_preuve_complete)
    r = comparer([{"event_id": "fill-0", "decision": "ACCEPT", "signal_age_ms": 30_000}],
                 d.run([_fill(0)]))
    assert "gain TECHNIQUE" in r["avertissement"]
    assert "n'est PAS acquis" in r["avertissement"]
    assert r["real_execution"] is False


def test_an_empty_comparison_never_crashes():
    r = comparer([], [])
    assert r["evenements_communs"] == 0
    assert r["taux_divergence"] is None
