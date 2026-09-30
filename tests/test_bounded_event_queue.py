"""NE JAMAIS PERDRE UN FILL EN SILENCE (2026-07-11) — Phase 5 du brief.

LE BUG DE LA QUEUE EXISTANTE (`realtime/low_latency_event_queue.py`) :

    if len(self._heap) >= self.max_size:
        heapq.heappop(self._heap)     # jette le PLUS ANCIEN
        self.dropped += 1             # et incrémente un compteur

Deux fautes, et la seconde est pire :

1. **Elle jette le plus ANCIEN** — exactement celui qu'on allait traiter. Sous charge, le système
   devient aveugle à ce qui vient d'arriver.
2. **Elle ne distingue RIEN.** Un `userFill` de leader — l'événement le plus précieux du système,
   celui sur lequel repose tout le Sniper — est jeté avec la même indifférence qu'un énième
   snapshot de prix dont seul le dernier compte.

Un drop silencieux, c'est un signal qu'on ne verra **jamais** et une perte qu'on n'expliquera
**jamais**.

Aucun ordre réel.
"""
from __future__ import annotations

from hl_observer.runtime.bounded_event_queue import (
    COALESCABLE,
    JAMAIS_JETABLE,
    BoundedEventQueue,
    Event,
    classer,
)

T0 = 1_800_000_000_000


def _fill(i: int) -> Event:
    return Event(event_id=f"fill-{i}", event_type="userFill", event_time_ms=T0 + i,
                 payload={"coin": "BTC"})


def _mid(i: int, coin: str = "BTC") -> Event:
    return Event(event_id=f"mid-{i}", event_type="allMids", event_time_ms=T0 + i,
                 payload={"coin": coin}, coalesce_key=coin)


# ------------------------------------------------------------------ LE contrat

def test_a_userFill_is_NEVER_dropped_even_when_the_queue_is_full():
    """LE TEST QUI COMPTE. La file est pleine de fills. Un fill de plus arrive.
    On dépasse la borne et on CRIE — on ne le jette pas. Perdre ce signal serait pire que
    dépasser la limite : on ne saurait même pas qu'on l'a perdu."""
    q = BoundedEventQueue(max_size=3)
    for i in range(3):
        assert q.push(_fill(i)) == "ACCEPTED"

    sort = q.push(_fill(99))
    assert sort == "BACKPRESSURE"
    assert q.backpressured is True
    assert q.metrics.jamais_jetables_perdus == 0, "un userFill a été perdu"
    # et il est bien LÀ, pas dans la nature
    ids = []
    while (e := q.pop()) is not None:
        ids.append(e.event_id)
    assert "fill-99" in ids


def test_a_price_snapshot_CAN_be_dropped_to_save_a_fill():
    """Un snapshot de prix intermédiaire ne vaut rien : seul le dernier compte. Il cède la place."""
    q = BoundedEventQueue(max_size=2)
    q.push(Event("m1", "allMids", T0, coalesce_key="ETH"))
    q.push(Event("m2", "allMids", T0 + 1, coalesce_key="SOL"))

    assert q.push(_fill(1)) == "ACCEPTED"          # le fill entre, un snapshot a cédé
    assert q.metrics.jetes == 1
    assert q.metrics.jamais_jetables_perdus == 0


def test_the_OLDEST_event_is_the_one_we_PROCESS_not_the_one_we_drop():
    """LE BUG DE L'ANCIENNE QUEUE : elle jetait le plus ancien. C'est-à-dire celui qu'on allait
    traiter. On sort en FIFO — le plus ancien d'abord."""
    q = BoundedEventQueue(max_size=10)
    for i in range(3):
        q.push(_fill(i))
    assert q.pop().event_id == "fill-0"
    assert q.pop().event_id == "fill-1"


# ------------------------------------------------------------------ coalescence

def test_only_the_LAST_price_snapshot_survives():
    """3 mids sur BTC : seul le dernier a une valeur. Garder les intermédiaires ne sert à rien."""
    q = BoundedEventQueue(max_size=10)
    q.push(_mid(1))
    q.push(_mid(2))
    q.push(_mid(3))
    assert q.depth() == 1
    assert q.metrics.coalesces == 2
    assert q.pop().event_id == "mid-3"


def test_coalescing_never_merges_two_different_coins():
    q = BoundedEventQueue(max_size=10)
    q.push(_mid(1, "BTC"))
    q.push(_mid(2, "ETH"))
    assert q.depth() == 2


def test_fills_are_NEVER_coalesced():
    """Deux fills de leader sont deux INFORMATIONS. Les fusionner en perdrait une."""
    q = BoundedEventQueue(max_size=10)
    q.push(_fill(1))
    q.push(_fill(2))
    assert q.depth() == 2
    assert q.metrics.coalesces == 0


def test_the_classification_is_explicit():
    assert classer("userFill") == JAMAIS_JETABLE
    assert classer("leader_close") == JAMAIS_JETABLE
    assert classer("allMids") == COALESCABLE
    assert classer("un_type_inconnu") == "DROPPABLE"


# ------------------------------------------------------------------ déduplication et ordre

def test_a_replayed_snapshot_is_NOT_a_new_fill():
    """Après une reconnexion, le WS renvoie un snapshot. Le rejouer comme des fills neufs
    fabriquerait des signaux qui n'ont jamais eu lieu."""
    q = BoundedEventQueue(max_size=10)
    assert q.push(_fill(1)) == "ACCEPTED"
    assert q.push(_fill(1)) == "DUPLICATE"
    assert q.depth() == 1
    assert q.metrics.doublons == 1


def test_an_out_of_order_event_is_counted_but_KEPT():
    """Hors ordre ≠ invalide. On le compte (c'est un symptôme), mais on ne le jette pas :
    ce serait perdre une donnée réelle."""
    q = BoundedEventQueue(max_size=10)
    q.push(_fill(10))
    q.push(_fill(2))                                # arrive après, mais plus ancien
    assert q.metrics.hors_ordre == 1
    assert q.depth() == 2


# ------------------------------------------------------------------ observabilité

def test_a_growing_backlog_invalidates_freshness():
    """Un signal qui attend 30 s dans une file n'est PLUS un signal frais, quoi qu'en dise sa
    date d'origine. Le backlog doit être visible."""
    q = BoundedEventQueue(max_size=10)
    q.push(_fill(0))
    h = q.health(now_ms=T0 + 30_000, max_lag_ms=5_000)
    assert h["oldest_event_age_ms"] >= 30_000
    assert h["lag_depasse"] is True


def test_the_never_dropped_counter_is_the_one_that_must_stay_at_zero():
    """Ce n'est pas une métrique parmi d'autres. Si elle bouge, un signal a été perdu."""
    q = BoundedEventQueue(max_size=2)
    for i in range(10):
        q.push(_fill(i))
    h = q.health(now_ms=T0 + 100)
    assert h["jamais_jetables_perdus"] == 0
    assert h["backpressured"] is True, "la surcharge doit être VISIBLE, pas silencieuse"


def test_every_drop_is_counted_never_silent():
    q = BoundedEventQueue(max_size=1)
    q.push(Event("x1", "type_inconnu", T0))
    q.push(Event("x2", "type_inconnu", T0 + 1))
    assert q.metrics.jetes >= 1
    assert q.health(now_ms=T0)["metrics"]["jetes"] >= 1


def test_an_empty_queue_never_crashes():
    q = BoundedEventQueue(max_size=5)
    assert q.pop() is None
    assert q.oldest_event_age_ms(T0) is None
    assert q.health(now_ms=T0)["depth"] == 0
