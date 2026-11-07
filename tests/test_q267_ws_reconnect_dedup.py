"""Q-267 — Tests reconnexion WS (pas de doublon, backfill correct).

Vérifie que les modules de reconnexion/déduplication WS fonctionnent
sans doublon et avec backfill correct après reconnexion.
"""
from __future__ import annotations

import pytest

from hl_observer.copy_vault.reconnect_overlap_backfill import (
    fenetre_backfill,
    reconnect_contract_receipt,
)
from hl_observer.copy_vault.reconnect_replay_suppression import (
    deduplicate_reconnect_fills,
    doit_creer_intent,
)


class TestBackfillWindow:
    def test_normal_overlap(self):
        r = fenetre_backfill(100_000, overlap_ms=5000)
        assert r["debut_ms"] == 95_000
        assert r["overlap_ms"] == 5000

    def test_invalid_checkpoint(self):
        r = fenetre_backfill("invalid")
        assert r["debut_ms"] == "UNMEASURABLE"

    def test_none_checkpoint(self):
        r = fenetre_backfill(None)
        assert r["debut_ms"] == "UNMEASURABLE"


class TestReplaySuppression:
    def test_new_event_creates_intent(self):
        r = doit_creer_intent(10, dernier_traite=5)
        assert r["creer"] is True

    def test_replay_suppressed(self):
        r = doit_creer_intent(5, dernier_traite=5)
        assert r["creer"] is False

    def test_old_event_suppressed(self):
        r = doit_creer_intent(3, dernier_traite=5)
        assert r["creer"] is False

    def test_invalid_seq_suppressed(self):
        r = doit_creer_intent("bad", dernier_traite=5)
        assert r["creer"] is False


class TestDeduplicateReconnectFills:
    def _fill(self, tid, ts_ms=1000, wallet="0xabc", coin="BTC"):
        return {"tid": tid, "ts_ms": ts_ms, "wallet": wallet, "coin": coin}

    def test_no_duplicates(self):
        fills = [self._fill(1), self._fill(2), self._fill(3)]
        r = deduplicate_reconnect_fills(fills)
        assert r["status"] == "PROVEN"
        assert r["retained_count"] == 3
        assert r["removed_duplicates"] == 0

    def test_exact_duplicate_removed(self):
        fills = [self._fill(1), self._fill(1), self._fill(2)]
        r = deduplicate_reconnect_fills(fills)
        assert r["status"] == "PROVEN"
        assert r["retained_count"] == 2
        assert r["removed_duplicates"] == 1

    def test_different_tid_same_ts_retained(self):
        fills = [self._fill(1, ts_ms=1000), self._fill(2, ts_ms=1000)]
        r = deduplicate_reconnect_fills(fills)
        assert r["retained_count"] == 2

    def test_invalid_fills_rejected(self):
        r = deduplicate_reconnect_fills("not a list")
        assert r["status"] == "UNMEASURABLE"

    def test_empty_list_ok(self):
        r = deduplicate_reconnect_fills([])
        assert r["status"] == "PROVEN"
        assert r["retained_count"] == 0


class TestReconnectContract:
    def test_valid_row(self):
        row = {
            "connection_id": "conn-1",
            "checkpoint_id": "chk-1",
            "event_id": "evt-1",
            "receive_ts_ms": 1000,
        }
        r = reconnect_contract_receipt(row)
        assert r["status"] == "PROVEN"

    def test_missing_field_rejected(self):
        row = {"connection_id": "conn-1", "receive_ts_ms": 1000}
        r = reconnect_contract_receipt(row)
        assert r["status"] == "REJECTED"
        assert r["fail_closed"] is True
