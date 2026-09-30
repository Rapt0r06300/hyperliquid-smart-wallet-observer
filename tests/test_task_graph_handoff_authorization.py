from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hl_observer.ops.task_graph_contract import acquire_ownership, transfer_ownership


def _now() -> datetime:
    return datetime(2026, 9, 10, 19, 35, tzinfo=timezone.utc)


def test_handoff_requires_current_owner_token() -> None:
    lease = acquire_ownership("H-T-49", "agent-a", now=_now(), ttl_seconds=60, token="old")

    with pytest.raises(PermissionError, match="active ownership credential required"):
        transfer_ownership(
            lease,
            current_owner="agent-a",
            current_token="wrong",
            new_owner="agent-b",
            now=_now() + timedelta(seconds=10),
            ttl_seconds=90,
            new_token="new",
        )


def test_handoff_cannot_reactivate_expired_lease() -> None:
    lease = acquire_ownership("H-T-49", "agent-a", now=_now(), ttl_seconds=60, token="old")

    with pytest.raises(PermissionError, match="active ownership credential required"):
        transfer_ownership(
            lease,
            current_owner="agent-a",
            current_token="old",
            new_owner="agent-b",
            now=_now() + timedelta(seconds=61),
            ttl_seconds=90,
            new_token="new",
        )
