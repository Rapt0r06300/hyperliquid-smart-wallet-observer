from __future__ import annotations

from hl_observer.backtesting.copy_vault_causal_selection import cluster_metaorders
from hl_observer.backtesting.copy_vault_protocol import canonical_metaorder_id


def _entry(event_id: str, action: str = "ADD") -> dict[str, object]:
    return {
        "event_id": event_id,
        "ts_ms": 2_000,
        "coin": "BTC",
        "direction": 1,
        "action": action,
        "dir": "Open Long",
        "vault": "0xA",
        "taille_usd": 10.0,
        "move_frac": 0.01,
    }


def _summary(rows: list[dict[str, object]]) -> list[tuple[object, ...]]:
    return [
        (
            row["metaorder_id"],
            tuple(row["member_event_ids"]),
            row["fill_count"],
            row["leader_notional_usd"],
        )
        for row in rows
    ]


def test_permutation_a_timestamp_egal_ne_change_pas_le_regroupement():
    first = [_entry("b"), _entry("a")]
    second = list(reversed(first))

    left, left_audit = cluster_metaorders(first)
    right, right_audit = cluster_metaorders(second)

    assert _summary(left) == _summary(right)
    assert left_audit["canonical_events"] == right_audit["canonical_events"] == 2
    assert left_audit["sliced_fills_collapsed"] == right_audit["sliced_fills_collapsed"] == 1


def test_tie_break_reste_deterministe_avec_open_et_add():
    rows, _audit = cluster_metaorders([_entry("z", "ADD"), _entry("a", "OPEN")])

    assert len(rows) == 1
    assert rows[0]["first_event_id"] == "a"
    assert rows[0]["member_event_ids"] == ["a", "z"]


def test_directions_opposees_a_timestamp_egal_restent_distinctes():
    common = {"vault": "0xA", "coin": "BTC", "signal_ts_ms": 2_000}
    long_id = canonical_metaorder_id(**common, direction=1, first_event_id="same-ts-long")
    short_id = canonical_metaorder_id(**common, direction=-1, first_event_id="same-ts-short")

    assert long_id != short_id
    assert long_id == canonical_metaorder_id(
        **common, direction=1, first_event_id="same-ts-long"
    )
