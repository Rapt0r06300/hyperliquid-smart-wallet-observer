from hl_observer.realtime.low_latency_event_queue import LowLatencyEventQueue, QueuedEvent


def test_low_latency_event_queue_orders_and_marks_late():
    queue = LowLatencyEventQueue(max_size=10, late_after_ms=100)
    queue.push(QueuedEvent(200, "b", {}), now_ms=250)
    queue.push(QueuedEvent(100, "a", {}), now_ms=250)
    rows = queue.drain()
    assert [row.event_id for row in rows] == ["a", "b"]
    assert rows[0].late is True
