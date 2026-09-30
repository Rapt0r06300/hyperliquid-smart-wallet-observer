from __future__ import annotations

from hl_observer.ops.dataset_bridge import PRESET_PATTERNS


def test_economic_core_contient_les_sources_copy_vault() -> None:
    patterns = PRESET_PATTERNS["economic-core"]
    assert "runtime/data/vault_fills.jsonl" in patterns
    assert "runtime/data/vault_fills_live.jsonl" in patterns
    assert "runtime/data/vault_ledger.jsonl" in patterns
    assert "runtime/data/vault_episodes.jsonl" in patterns
    assert "runtime/data/vault_snapshots.jsonl" in patterns
    assert "runtime/data/copy_vault_l2_tape.jsonl" in patterns


def test_economic_core_contient_les_sources_lead_lag() -> None:
    patterns = PRESET_PATTERNS["economic-core"]
    assert "runtime/data/bbo_tape.jsonl" in patterns
    assert "runtime/data/bbo_shards/" in patterns
    assert "runtime/data/bbo_shards_archive/" in patterns


def test_economic_core_contient_la_source_cross_venue() -> None:
    patterns = PRESET_PATTERNS["economic-core"]
    assert "runtime/data/carnet_venues.jsonl" in patterns
