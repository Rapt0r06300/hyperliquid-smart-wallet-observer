from hl_observer.arbitrage.double_budget_reservation import ReservationBudget
from hl_observer.copy_vault.ambiguous_action_deny import decision as ambiguous_decision
from hl_observer.copy_vault.authoritative_close_direction import direction_reduction
from hl_observer.copy_vault.drop_stale_open_add import DROP, decision as stale_decision
from hl_observer.copy_vault.holding_time_compatibility import evaluer
from hl_observer.copy_vault.max_concurrent_positions import LimiteurPositions
from hl_observer.copy_vault.per_vault_queue_cap import LimiteurQueueVault
from hl_observer.copy_vault.vault_heartbeat import HeartbeatVaults


def test_double_budget_refuses_duplicate_episode_without_reserving_twice() -> None:
    budget = ReservationBudget(10.0)
    assert budget.reserver_episode("episode-1", capital_a=2.0, capital_b=2.0, frais=0.25)["ok"] is True

    result = budget.reserver_episode("episode-1", capital_a=1.0, capital_b=1.0, frais=0.0)

    assert result == {
        "ok": False,
        "raison": "EPISODE_DEJA_RESERVE",
        "disponible": 5.75,
    }
    assert budget.disponible() == 5.75


def test_clear_reduction_never_creates_new_exposure() -> None:
    result = ambiguous_decision("REDUCE", confiance=None)

    assert result == {
        "nouvelle_exposition": False,
        "autorise_reduction": True,
        "raison": "REDUCTION",
    }


def test_reduction_rejects_non_positive_quantity() -> None:
    assert direction_reduction(2.0, 0.0) == {
        "direction": None,
        "raison": "QUANTITE_INVALIDE",
    }


def test_open_with_unknown_age_is_dropped_fail_closed() -> None:
    result = stale_decision("OPEN", None, ttl_ms=1_000.0)

    assert result == {
        "decision": DROP,
        "missed_opportunity": True,
        "raison": "AGE_INCONNU",
    }


def test_position_limiter_refuses_first_new_coin_when_cap_is_zero() -> None:
    limiter = LimiteurPositions(max_positions=0)

    assert limiter.ouvrir("BTC") is False
    assert limiter.peut_ouvrir("BTC")["raison"] == "PLAFOND_POSITIONS_ATTEINT"


def test_vault_queue_limiter_refuses_enqueue_when_cap_is_zero() -> None:
    limiter = LimiteurQueueVault(cap_par_vault=0)

    assert limiter.ajouter("vault-a") is False
    assert limiter.peut_ajouter("vault-a")["profondeur"] == 0


def test_holding_time_is_degraded_when_copy_latency_is_material() -> None:
    result = evaluer(10.0, latence_copie_s=5.0, ratio_degrade=0.2)

    assert result == {"etat": "DEGRADE", "ratio_latence_holding": 0.5}


def test_vault_heartbeat_fails_closed_on_invalid_clock_value() -> None:
    heartbeat = HeartbeatVaults()

    assert heartbeat.vivant("vault-a", now_ms="invalid") == {
        "vivant": False,
        "raison": "TEMPS_INVALIDE",
    }
