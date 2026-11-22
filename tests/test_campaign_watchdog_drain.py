from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tools.campaign_watchdog import (
    _dispatch_market_handoff,
    _dispatch_successor,
    _reconcile_drain_stuck,
    _reconcile_epoch_superseded,
    _reconcile_retry_current_epoch,
    _reconcile_finished_owner,
    _select_market_handoff_successor,
    _terminalize_superseded_stuck,
)


def _phase():
    return {
        "phase": "ANALYZE",
        "analysis_stage": "DRAIN",
        "epoch": 3,
        "source_collection_epoch": 2,
        "collection_cutoff_at_utc": "2026-09-29T10:56:59Z",
    }


def _row(*, completed=None, acquired_at="2026-09-29T10:52:00Z"):
    return {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "market-drain",
        "kind": "market_collection",
        "creation_phase": "COLLECT",
        "phase_epoch": 2,
        "status": "STUCK",
        "stuck_reason": "LEASE_EXPIRED_REQUIRES_RECONCILIATION",
        "lease": None,
        "completed_units": completed or {},
        "history": [{
            "event": "WATCHDOG_LEASE_EXPIRED",
            "previous_lease": {
                "acquired_at": acquired_at,
                "expires_at": "2026-09-29T16:37:00Z",
            },
        }],
    }


def test_drain_terminalizes_expired_claim_without_durable_progress():
    row = _row()
    assert _reconcile_drain_stuck(
        row, _phase(), datetime(2026, 9, 30, tzinfo=timezone.utc)
    )
    assert row["status"] == "UNAVAILABLE"
    assert row["status_reason"] == "DRAIN_CUTOFF_INTERRUPTED_WITHOUT_DURABLE_PROGRESS"
    assert row["lease"] is None
    assert len(row["terminal_evidence_digest"]) == 64


def test_drain_preserves_durable_progress_as_partial():
    row = _row(completed={"0": {"sha256": "a" * 64}})
    assert _reconcile_drain_stuck(
        row, _phase(), datetime(2026, 9, 30, tzinfo=timezone.utc)
    )
    assert row["status"] == "PARTIAL"
    assert row["status_reason"] == "DRAIN_CUTOFF_INTERRUPTED_AFTER_DURABLE_PROGRESS"


def test_drain_rejects_claim_started_after_cutoff():
    row = _row(acquired_at="2026-09-29T11:00:00Z")
    assert _reconcile_drain_stuck(
        row, _phase(), datetime(2026, 9, 30, tzinfo=timezone.utc)
    )
    assert row["status"] == "FAILED"
    assert row["status_reason"] == "DRAIN_CLAIM_STARTED_AFTER_CUTOFF"


def test_non_drain_phase_does_not_rewrite_stuck_campaign():
    row = _row()
    phase = _phase()
    phase["analysis_stage"] = "QUALITY"
    assert not _reconcile_drain_stuck(
        row, phase, datetime(2026, 9, 30, tzinfo=timezone.utc)
    )
    assert row["status"] == "STUCK"

def test_finished_owner_run_revokes_live_lease_immediately():
    row = {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "analysis-e3-resume-proof-v1",
        "kind": "replay",
        "status": "RUNNING",
        "lease": {
            "owner_run_id": "12345",
            "acquired_at": "2026-09-30T13:00:00Z",
            "expires_at": "2026-09-30T19:00:00Z",
        },
        "history": [],
    }
    now = datetime(2026, 9, 30, 13, 30, tzinfo=timezone.utc)
    assert _reconcile_finished_owner(
        row,
        now,
        run_state=lambda run_id: ("completed", "failure"),
    )
    assert row["lease"] is None
    assert row["status"] == "STUCK"
    assert row["status_reason"] == "OWNER_RUN_COMPLETED_WITH_ACTIVE_LEASE"
    assert row["stuck_reason"] == "OWNER_RUN_COMPLETED_WITH_ACTIVE_LEASE"
    assert row["history"][-1]["owner_run_id"] == "12345"
    assert row["history"][-1]["owner_run_conclusion"] == "failure"


def test_active_owner_run_keeps_live_lease():
    row = {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "analysis-e3-replay-v2",
        "kind": "replay",
        "status": "RUNNING",
        "lease": {"owner_run_id": "999", "expires_at": "2026-09-30T19:00:00Z"},
        "history": [],
    }
    now = datetime(2026, 9, 30, 13, 30, tzinfo=timezone.utc)
    assert not _reconcile_finished_owner(
        row,
        now,
        run_state=lambda run_id: ("in_progress", ""),
    )
    assert row["status"] == "RUNNING"
    assert row["lease"]["owner_run_id"] == "999"

def test_dispatch_successor_retries_transient_rate_limit(monkeypatch):
    row = {
        "campaign_id": "market-retry",
        "phase_epoch": 7,
        "chunk_index": 3,
        "cursor": {"last_run_id": ""},
    }
    calls = []
    responses = [
        SimpleNamespace(returncode=1, stderr="HTTP 403: API rate limit exceeded for installation", stdout=""),
        SimpleNamespace(returncode=0, stderr="", stdout=""),
    ]

    def fake_run(command, **kwargs):
        calls.append(command)
        return responses.pop(0)

    sleeps = []
    monkeypatch.setattr("tools.campaign_watchdog.subprocess.run", fake_run)
    monkeypatch.setattr("tools.campaign_watchdog.time.sleep", lambda seconds: sleeps.append(seconds))

    ok, detail = _dispatch_successor(
        row,
        "Rapt0r06300/hyperliquid-smart-wallet-observer",
        datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc),
    )

    assert ok is True
    assert detail == "dispatched"
    assert len(calls) == 2
    assert sleeps == [5]
    assert row["cursor"]["successor_dispatch_at_utc"] == "2026-10-01T14:00:00Z"


def test_dispatch_successor_stops_after_bounded_transient_retries(monkeypatch):
    row = {
        "campaign_id": "market-retry-bounded",
        "phase_epoch": 7,
        "chunk_index": 4,
        "cursor": {"last_run_id": ""},
    }
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=1,
            stderr="HTTP 403: API rate limit exceeded for installation",
            stdout="",
        )

    sleeps = []
    monkeypatch.setattr("tools.campaign_watchdog.subprocess.run", fake_run)
    monkeypatch.setattr("tools.campaign_watchdog.time.sleep", lambda seconds: sleeps.append(seconds))

    ok, detail = _dispatch_successor(
        row,
        "Rapt0r06300/hyperliquid-smart-wallet-observer",
        datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc),
    )

    assert ok is False
    assert "bounded transient dispatch retry exhausted" in detail
    assert len(calls) == 6
    assert sleeps == [5, 20, 45, 60, 60]
    assert "successor_dispatch_at_utc" not in row["cursor"]

def test_stuck_market_campaign_terminalizes_when_newer_equivalent_progresses():
    old = {
        "campaign_id": "market-e6-0-old",
        "kind": "market_collection",
        "status": "STUCK",
        "status_reason": "durable_publication_failed",
        "phase_epoch": 6,
        "created_at": "2026-10-01T04:55:00+00:00",
        "completed_units": {"0": {"sha256": "a" * 64}},
        "cursor": {
            "market_shard_index": 0,
            "universe_digest": "u" * 64,
            "plan_sha256": "p" * 64,
        },
        "history": [],
    }
    replacement = {
        "campaign_id": "market-e6-0-new",
        "kind": "market_collection",
        "status": "RUNNING",
        "attempts": 1,
        "phase_epoch": 6,
        "created_at": "2026-10-01T05:07:00+00:00",
        "lease": {"owner_run_id": "123"},
        "cursor": {
            "market_shard_index": 0,
            "universe_digest": "u" * 64,
            "plan_sha256": "p" * 64,
        },
    }

    assert _terminalize_superseded_stuck(
        old, replacement, datetime(2026, 10, 1, 15, 10, tzinfo=timezone.utc)
    )
    assert old["status"] == "FAILED"
    assert old["status_reason"] == "SUPERSEDED_BY_NEWER_MARKET_CAMPAIGN"
    assert old["history"][-1]["replacement_campaign_id"] == "market-e6-0-new"
    assert len(old["terminal_evidence_digest"]) == 64


def test_stuck_market_campaign_not_hidden_by_unprogressed_replacement():
    old = {
        "campaign_id": "market-e6-0-old",
        "kind": "market_collection",
        "status": "STUCK",
        "phase_epoch": 6,
        "created_at": "2026-10-01T04:55:00+00:00",
        "cursor": {
            "market_shard_index": 0,
            "universe_digest": "u" * 64,
            "plan_sha256": "p" * 64,
        },
        "history": [],
    }
    replacement = {
        "campaign_id": "market-e6-0-new",
        "kind": "market_collection",
        "status": "PENDING",
        "attempts": 0,
        "phase_epoch": 6,
        "created_at": "2026-10-01T05:07:00+00:00",
        "cursor": {
            "market_shard_index": 0,
            "universe_digest": "u" * 64,
            "plan_sha256": "p" * 64,
        },
    }

    assert not _terminalize_superseded_stuck(
        old, replacement, datetime(2026, 10, 1, 15, 10, tzinfo=timezone.utc)
    )
    assert old["status"] == "STUCK"

def _market_handoff_row(
    campaign_id: str,
    *,
    shard: int,
    status: str,
    created_at: str,
    acquired_at: str | None = None,
    owner_run_id: str | None = None,
):
    lease = None
    if acquired_at is not None:
        lease = {
            "acquired_at": acquired_at,
            "expires_at": "2026-10-04T06:00:00Z",
            "owner_run_id": owner_run_id or "run-predecessor",
        }
    return {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": campaign_id,
        "kind": "market_collection",
        "creation_phase": "COLLECT",
        "phase_epoch": 6,
        "status": status,
        "created_at": created_at,
        "updated_at": created_at,
        "chunk_index": 0,
        "lease": lease,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "cursor": {
            "duration_s": 3500,
            "market_shard_count": 16,
            "market_shard_index": shard,
            "universe_digest": "a" * 64,
            "plan_sha256": "b" * 64,
        },
        "history": [],
    }


def test_market_handoff_selects_newest_pending_same_shard_when_due():
    predecessor = _market_handoff_row(
        "market-old",
        shard=3,
        status="RUNNING",
        created_at="2026-10-04T00:00:00Z",
        acquired_at="2026-10-04T00:00:00Z",
    )
    older = _market_handoff_row(
        "market-next-1",
        shard=3,
        status="PENDING",
        created_at="2026-10-04T00:20:00Z",
    )
    newest = _market_handoff_row(
        "market-next-2",
        shard=3,
        status="PENDING",
        created_at="2026-10-04T00:35:00Z",
    )
    wrong_shard = _market_handoff_row(
        "market-wrong",
        shard=4,
        status="PENDING",
        created_at="2026-10-04T00:40:00Z",
    )

    successor, reason = _select_market_handoff_successor(
        predecessor,
        [older, newest, wrong_shard],
        datetime(2026, 10, 4, 0, 48, tzinfo=timezone.utc),
    )

    assert reason == "handoff_ready"
    assert successor is newest


def test_market_handoff_does_not_dispatch_too_early():
    predecessor = _market_handoff_row(
        "market-old",
        shard=3,
        status="RUNNING",
        created_at="2026-10-04T00:00:00Z",
        acquired_at="2026-10-04T00:00:00Z",
    )
    successor = _market_handoff_row(
        "market-next",
        shard=3,
        status="PENDING",
        created_at="2026-10-04T00:10:00Z",
    )

    selected, reason = _select_market_handoff_successor(
        predecessor,
        [successor],
        datetime(2026, 10, 4, 0, 20, tzinfo=timezone.utc),
    )

    assert selected is None
    assert reason == "handoff_not_due"


def test_dispatch_market_handoff_targets_distinct_successor_and_records_lineage(monkeypatch):
    predecessor = _market_handoff_row(
        "market-old",
        shard=3,
        status="RUNNING",
        created_at="2026-10-04T00:00:00Z",
        acquired_at="2026-10-04T00:00:00Z",
        owner_run_id="123456",
    )
    successor = _market_handoff_row(
        "market-next",
        shard=3,
        status="PENDING",
        created_at="2026-10-04T00:30:00Z",
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("tools.campaign_watchdog.subprocess.run", fake_run)

    ok, detail = _dispatch_market_handoff(
        predecessor,
        successor,
        "Rapt0r06300/hyperliquid-smart-wallet-observer",
        datetime(2026, 10, 4, 0, 48, tzinfo=timezone.utc),
    )

    assert ok is True
    assert detail == "handoff_dispatched"
    command = calls[0]
    assert "campaign_id=market-next" in command
    assert "predecessor_run_id=123456" in command
    assert "generation=1" in command
    assert predecessor["cursor"]["hot_handoff_successor_campaign_id"] == "market-next"
    assert predecessor["history"][-1]["event"] == "HOT_HANDOFF_SUCCESSOR_DISPATCHED"



# ---------------------------------------- EPOQUE DEPASSEE (mesure du 21/11/2026)
def _phase_courante(epoch: int = 8):
    """L'etat REEL mesure le 21/11/2026 : COLLECT, sans cutoff, sans epoque source."""
    return {
        "phase": "COLLECT",
        "analysis_stage": None,
        "epoch": epoch,
        "source_collection_epoch": None,
        "collection_cutoff_at_utc": None,
    }


def _row_abandonnee(*, epoch=4, status="STUCK", lease=None, completed=None):
    """Une campagne de l'epoque 4, telle que `copy-vault-12-2026100104-v7`."""
    return {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "copy-vault-12-2026100104-v7",
        "kind": "copy_vault_collection",
        "creation_phase": "COLLECT",
        "phase_epoch": epoch,
        "status": status,
        "status_reason": "OWNER_RUN_COMPLETED_WITH_ACTIVE_LEASE",
        "stuck_reason": "OWNER_RUN_COMPLETED_WITH_ACTIVE_LEASE",
        "lease": lease,
        "completed_units": completed or {},
        "history": [],
    }


def _maintenant():
    return datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc)


def test_une_campagne_d_epoque_depassee_est_isolee_et_non_laissee_en_attente():
    """13 campagnes etaient figees depuis le 07/10 : terminales mais INCLOSABLES.

    `_reconcile_finished_owner` revoque la lease et marque STUCK en comptant sur le
    controleur pour reconcilier ; le controleur est passe de l'epoque 4 a 8 sans jamais
    drainer. `_reconcile_drain_stuck` exige un autre motif, ANALYZE/DRAIN, un cutoff et
    l'egalite d'epoque : aucun chemin ne pouvait plus les fermer.
    """
    row = _row_abandonnee()
    assert _reconcile_epoch_superseded(row, _phase_courante(), _maintenant()) is True
    assert row["status"] == "UNAVAILABLE"
    assert row["status_reason"] == "EPOCH_SUPERSEDED_COLLECTION_WINDOW_CLOSED"
    assert row["stuck_reason"] is None
    evenement = row["history"][-1]
    assert evenement["event"] == "WATCHDOG_EPOCH_SUPERSEDED_TERMINALIZED"
    assert evenement["previous_status"] == "STUCK"
    assert evenement["campaign_phase_epoch"] == 4
    assert evenement["controller_epoch"] == 8
    assert len(row["terminal_evidence_digest"]) == 64


def test_le_travail_deja_fait_n_est_jamais_rabaisse_a_rien():
    """4 des 295 campagnes mesurees portaient des unites faites : elles finissent PARTIAL."""
    row = _row_abandonnee(completed={"u0": {"shards": 3}})
    assert _reconcile_epoch_superseded(row, _phase_courante(), _maintenant()) is True
    assert row["status"] == "PARTIAL"
    assert row["status_reason"] == "EPOCH_SUPERSEDED_WITH_DURABLE_PROGRESS"
    assert row["completed_units"] == {"u0": {"shards": 3}}


def test_l_epoque_courante_n_est_jamais_touchee():
    """La mesure du 21/11 laisse 66 PENDING et 8 STUCK de l'epoque courante intacts."""
    row = _row_abandonnee(epoch=8)
    assert _reconcile_epoch_superseded(row, _phase_courante(8), _maintenant()) is False
    assert row["status"] == "STUCK"


def test_une_campagne_reclamee_par_quelqu_un_n_est_pas_fermee():
    """Une lease vivante est le travail en cours d'un autre : on n'y touche pas."""
    row = _row_abandonnee(lease={"owner_run_id": "123", "acquired_at": "2026-11-21T19:00:00Z"})
    assert _reconcile_epoch_superseded(row, _phase_courante(), _maintenant()) is False
    assert row["status"] == "STUCK"


def test_un_statut_deja_terminal_reste_tel_quel():
    for statut in ("COMPLETE", "FAILED", "UNAVAILABLE", "PARTIAL"):
        row = _row_abandonnee(status=statut)
        assert _reconcile_epoch_superseded(row, _phase_courante(), _maintenant()) is False
        assert row["status"] == statut


def test_un_schema_ancien_ou_une_epoque_illisible_ne_declenche_rien():
    ancien = _row_abandonnee()
    ancien["schema_version"] = "alina.resumable_campaign.v1"
    assert _reconcile_epoch_superseded(ancien, _phase_courante(), _maintenant()) is False
    sans_epoque = _row_abandonnee()
    sans_epoque["phase_epoch"] = None
    assert _reconcile_epoch_superseded(sans_epoque, _phase_courante(), _maintenant()) is False
    futur = _row_abandonnee(epoch=9)
    assert _reconcile_epoch_superseded(futur, _phase_courante(8), _maintenant()) is False


# -------------------------------- REPRISE bornee de l'epoque courante (21/11/2026)
def test_une_campagne_de_l_epoque_courante_est_REPRISE_et_non_isolee():
    """8 campagnes de l'epoque 8 etaient figees depuis le 01-07/11, lease nulle.

    Leur fenetre de collecte est encore OUVERTE : les isoler jetterait des donnees
    encore collectables. `_reconcile_finished_owner` annonce << reconcile OR RETRY >> ;
    personne ne reprenait.
    """
    row = _row_abandonnee(epoch=8, status="STUCK", completed={"u0": {"shards": 2}})
    assert _reconcile_retry_current_epoch(row, _phase_courante(8), _maintenant()) is True
    assert row["status"] == "PENDING"
    assert row["status_reason"] == "RETRY_AFTER_OWNER_RUN_DEATH"
    assert row["stuck_reason"] is None
    assert row["watchdog_retries"] == 1
    # La reprise RESUME : le travail durable n'est pas jete.
    assert row["completed_units"] == {"u0": {"shards": 2}}
    assert row["history"][-1]["event"] == "WATCHDOG_RETRY_CURRENT_EPOCH"
    assert row["history"][-1]["preserved_completed_units"] == ["u0"]


def test_la_reprise_est_BORNEE_et_son_epuisement_est_nomme():
    """Sans plafond, une campagne qui tue ses runners serait relancee sans fin."""
    row = _row_abandonnee(epoch=8, status="STUCK")
    row["watchdog_retries"] = 3
    assert _reconcile_retry_current_epoch(row, _phase_courante(8), _maintenant()) is True
    assert row["status"] == "FAILED"
    assert row["status_reason"] == "RETRIES_EXHAUSTED_AFTER_OWNER_RUN_FAILURES"
    assert row["history"][-1]["event"] == "WATCHDOG_RETRIES_EXHAUSTED"
    assert len(row["terminal_evidence_digest"]) == 64


def test_l_epuisement_preserve_le_travail_deja_fait():
    row = _row_abandonnee(epoch=8, status="STUCK", completed={"u1": {"shards": 9}})
    row["watchdog_retries"] = 3
    assert _reconcile_retry_current_epoch(row, _phase_courante(8), _maintenant()) is True
    assert row["status"] == "PARTIAL"
    assert row["completed_units"] == {"u1": {"shards": 9}}


def test_les_deux_reconciliations_ne_se_chevauchent_jamais():
    """Une epoque depassee s'isole, une epoque courante se reprend : jamais l'inverse."""
    depassee = _row_abandonnee(epoch=4, status="STUCK")
    assert _reconcile_retry_current_epoch(depassee, _phase_courante(8), _maintenant()) is False
    courante = _row_abandonnee(epoch=8, status="STUCK")
    assert _reconcile_epoch_superseded(courante, _phase_courante(8), _maintenant()) is False


def test_la_reprise_ne_touche_ni_une_lease_vivante_ni_un_autre_motif():
    avec_lease = _row_abandonnee(epoch=8, status="STUCK",
                                 lease={"owner_run_id": "9", "acquired_at": "2026-11-21T19:00:00Z"})
    assert _reconcile_retry_current_epoch(avec_lease, _phase_courante(8), _maintenant()) is False
    autre_motif = _row_abandonnee(epoch=8, status="STUCK")
    autre_motif["stuck_reason"] = "LEASE_EXPIRED_REQUIRES_RECONCILIATION"
    assert _reconcile_retry_current_epoch(autre_motif, _phase_courante(8), _maintenant()) is False
