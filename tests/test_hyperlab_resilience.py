"""[Bloc 25-28/33] Collecteurs supervises + resilience + DLQ."""
from hl_observer.hyperlab import collectors as c
from hl_observer.hyperlab.dlq import DeadLetterQueue


def test_collector_health_states():
    col = c.SupervisedCollector("bybit_book", pid=111)
    assert col.health(100, seuil_heartbeat_s=10, seuil_useful_s=10) == c.DEAD  # jamais demarre
    col.battement(100)
    assert col.health(105, seuil_heartbeat_s=10, seuil_useful_s=10) == c.NO_DATA  # heartbeat sans donnee
    col.evenement(106, utile=True)
    assert col.health(108, seuil_heartbeat_s=10, seuil_useful_s=10) == c.OK
    assert col.health(200, seuil_heartbeat_s=10, seuil_useful_s=10) == c.DEAD  # plus de heartbeat
    col.battement(205)
    assert col.health(206, seuil_heartbeat_s=10, seuil_useful_s=10) == c.STALE  # vivant mais donnee vieille


def test_collector_success_exige_donnee_utile():
    col = c.SupervisedCollector("x", 1)
    col.battement(100)  # vivant mais 0 utile
    assert col.est_success(101, seuil_heartbeat_s=10, seuil_useful_s=10) is False
    col.evenement(102, utile=True)
    assert col.est_success(103, seuil_heartbeat_s=10, seuil_useful_s=10) is True


def test_reconnect_backoff_borne():
    p = c.ReconnectPolicy(base_s=1.0, cap_s=10.0)
    assert [p.delay(n) for n in range(6)] == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]


def test_circuit_breaker():
    cb = c.CircuitBreaker(seuil=2, cooldown_s=5.0)
    assert cb.autorise(0)
    cb.echec(1); cb.echec(2)
    assert cb.etat == "open" and cb.autorise(3) is False
    assert cb.autorise(10) is True and cb.etat == "half"  # cooldown ecoule
    cb.succes()
    assert cb.etat == "closed"


def test_rate_limit_coordinator():
    rl = c.RateLimitCoordinator(capacite=2, fenetre_s=10.0)
    assert rl.acquire(0) and rl.acquire(1)
    assert rl.acquire(2) is False           # fenetre pleine
    assert rl.acquire(12) is True           # anciens expires


def test_bounded_queue_load_shedding():
    q = c.BoundedQueue(maxlen=2)
    q.push("a", priorite=1); q.push("b", priorite=1)
    r = q.push("c", priorite=5)             # plein -> jette la plus basse priorite
    assert r["accepte"] and r["rejete"] in ("a", "b") and len(q) == 2
    r2 = q.push("d", priorite=0)            # priorite trop basse -> refuse d lui-meme
    assert r2["accepte"] is False and r2["rejete"] == "d"


def test_disk_quota():
    dq = c.DiskQuota(max_bytes=100)
    assert dq.add(60) and dq.add(40)
    assert dq.add(1) is False


def test_dlq_quarantaine():
    dlq = DeadLetterQueue()
    def parser(b):
        if b == "bad":
            raise ValueError("boom")
        return None if b == "empty" else {"ok": b}
    assert dlq.parse_ou_dlq("bad", parser, source="bybit") is None
    assert dlq.parse_ou_dlq("empty", parser, source="okx") is None
    assert dlq.parse_ou_dlq("good", parser, source="okx") == {"ok": "good"}
    assert len(dlq) == 2 and dlq.par_source() == {"bybit": 1, "okx": 1}
