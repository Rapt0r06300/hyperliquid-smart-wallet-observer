"""LATENCE : NE JAMAIS MÉLANGER DEUX HORLOGES (2026-07-11) — Phase 3 du brief.

CE QUI EXISTAIT : `latency_report.py` rapporte **un seul** chiffre, `signal_age_ms`, obtenu en
soustrayant un horodatage d'**exchange** d'une horloge **locale**. Les deux ne sont pas
synchronisées.

Conséquence : un décalage d'horloge de 200 ms se lit comme 200 ms de latence — **ou, pire, il peut
MASQUER 200 ms de vraie latence.** On mesure sa propre dérive d'horloge en croyant mesurer le réseau.

Ces tests verrouillent la séparation :

    « le signal était-il déjà vieux en arrivant ? »       → horloge murale, rapporté à part
    « combien de temps l'avons-nous gardé avant d'agir ? » → horloge MONOTONE, ce qu'on contrôle

**Les confondre, c'est ne pouvoir corriger ni l'un ni l'autre.**

Aucun ordre réel.
"""
from __future__ import annotations

import time

from hl_observer.runtime.latency_trace import ETAPES, LatencyTrace, resumer


def _trace_complete(*, source_ms: int | None = None) -> LatencyTrace:
    t = LatencyTrace(event_id="e1", coin="BTC", source="userFills",
                     source_event_time_ms=source_ms)
    t.start()
    for etape in ("decode", "normalize", "dedupe", "state_update", "features",
                  "signal", "score", "gates", "decision"):
        t.stamp(etape)
    return t


# ------------------------------------------------------------------ la séparation des horloges

def test_local_duration_uses_a_monotonic_clock_not_the_wall_clock():
    """LE CŒUR. Une durée locale doit venir d'une horloge qui ne recule jamais."""
    t = LatencyTrace().start()
    time.sleep(0.002)
    t.stamp("decision")
    d = t.local_processing_ms()
    assert d is not None and d >= 1.5, "la durée locale n'est pas mesurée"
    # une horloge monotone ne rend JAMAIS une durée négative, même si l'heure système change
    assert d > 0


def test_the_source_age_is_reported_SEPARATELY_never_added():
    """Les deux nombres répondent à deux questions. Les additionner mélangerait deux référentiels."""
    maintenant_ms = int(time.time() * 1000)
    t = _trace_complete(source_ms=maintenant_ms - 30_000)     # signal vieux de 30 s
    d = t.as_dict()

    assert d["source_age_ms"] >= 29_000                        # l'âge SOURCE est là
    assert d["local_processing_ms"] < 100                      # le traitement LOCAL est minuscule
    # et il n'existe NULLE PART un champ qui les additionne
    assert "total_ms" not in d and "latence_totale_ms" not in d
    assert "MONOTONE" in d["clock_note"]


def test_a_missing_source_timestamp_yields_None_not_zero():
    """VÉRITÉ : sans horodatage exchange, on NE SAIT PAS l'âge. On ne rend pas « 0 »."""
    t = _trace_complete(source_ms=None)
    assert t.source_age_ms() is None
    assert t.local_processing_ms() is not None                 # mais le local, lui, est mesuré


# ------------------------------------------------------------------ chaque étape est mesurée

def test_every_stage_of_the_hot_path_is_measurable():
    """Le cycle médian est à 30,6 s. Le temps ne se perd pas « quelque part » : il se perd à des
    endroits PRÉCIS. Sans mesure par étape, on ne peut que deviner lequel."""
    t = _trace_complete()
    etapes = t.stage_durations_ms()
    assert "receive->decode" in etapes
    assert "gates->decision" in etapes
    assert all(v >= 0 for v in etapes.values())


def test_an_unstamped_stage_is_ABSENT_not_zero():
    """Un zéro silencieux ferait croire à une étape instantanée. L'absence doit rester une absence."""
    t = LatencyTrace().start()
    t.stamp("decision")                                        # on saute tout le milieu
    etapes = t.stage_durations_ms()
    assert "receive->decision" in etapes
    assert "receive->decode" not in etapes, "une étape jamais horodatée est apparue avec une durée"


def test_an_unknown_stage_is_ignored_not_invented():
    t = LatencyTrace().start()
    t.stamp("une_etape_qui_n_existe_pas")
    assert not any("existe_pas" in k for k in t.stage_durations_ms())


# ------------------------------------------------------------------ le résumé ne flatte pas

def test_the_summary_reports_the_MISSING_rate():
    """Une médiane calculée sur 3 % des événements ne décrit pas le système. On le DIT."""
    traces = [_trace_complete(source_ms=int(time.time() * 1000) - 1_000) for _ in range(3)]
    traces += [_trace_complete(source_ms=None) for _ in range(7)]     # 7 sans horodatage source

    r = resumer(traces)
    assert r["evenements"] == 10
    assert r["age_source_ms"]["n"] == 3
    assert r["age_source_ms"]["manquants"] == 7
    assert r["age_source_ms"]["taux_manquant"] == 0.7, (
        "le taux de valeurs manquantes est caché : la médiane paraîtrait représentative"
    )


def test_the_summary_keeps_the_two_clocks_apart():
    r = resumer([_trace_complete(source_ms=int(time.time() * 1000) - 5_000)])
    assert "age_source_ms" in r and "traitement_local_ms" in r
    assert "decalage" in r["age_source_ms"]["mesure"] or "murale" in r["age_source_ms"]["mesure"]
    assert "MONOTONE" in r["traitement_local_ms"]["mesure"]


def test_percentiles_are_present_for_every_stage():
    traces = [_trace_complete() for _ in range(20)]
    r = resumer(traces)
    for _nom, stats in r["par_etape_ms"].items():
        for cle in ("mediane", "p90", "p95", "p99", "max"):
            assert cle in stats


def test_an_empty_run_never_crashes_and_never_invents():
    r = resumer([])
    assert r["evenements"] == 0
    assert r["age_source_ms"]["mediane"] is None
    assert r["traitement_local_ms"]["mediane"] is None
    assert r["real_execution"] is False


def test_the_stage_list_covers_the_whole_critical_path():
    """Si une étape du chemin critique n'est pas dans la liste, elle sera invisible à jamais."""
    for attendue in ("receive", "decode", "features", "gates", "decision"):
        assert attendue in ETAPES
