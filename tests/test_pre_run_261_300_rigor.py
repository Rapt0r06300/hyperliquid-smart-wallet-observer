from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from hl_observer.research.pre_run_261_300 import (
    PreRunInvariantError,
    agreger_sante_collecteurs,
    atomic_write_text,
    avancer_cursor_idempotent,
    calculer_notional_quote,
    canonicaliser_timestamp_ms,
    cle_dedup_coinbase,
    comparer_staleness_intervenue,
    configurer_sqlite_strict,
    construire_autopsie_incident,
    construire_catalogue_signaux,
    construire_evidence_bundle,
    construire_lineage_ledger,
    construire_symbol_master,
    correlation_id,
    cout_cross_venue_bps,
    detecter_discontinuite_alimentation,
    lire_prix_semantique,
    log_structure,
    normaliser_evenement_marche,
    nouveau_run_context,
    replay_deterministe,
    shadow_record_brut,
    transaction_sqlite_atomique,
    valider_archive_auditable,
    valider_book_granularity,
    valider_checkpoint,
    valider_data_contract,
    valider_fee_schedule,
    valider_reprise_checkpoint,
    valider_retention_reproductible,
    valider_schema_version,
    verifier_backpressure,
    verifier_budget_ressources,
    verifier_drift_horloge_locale,
    verifier_drift_lead_lag,
    verifier_provenance_forte,
    verifier_reprise_windows,
    verifier_run_id_commun,
    verifier_signaux_utilises,
)


def test_aud_261_262_catalogue_auto_et_signal_inconnu_fail_closed():
    cat = construire_catalogue_signaux([
        {"name": "lead_bbo", "family": "LEAD_LAG", "inputs": ["bbo"], "version": "1"},
        {"name": "xvenue_gap", "family": "CROSS_VENUE", "inputs": ["book"], "version": "1"},
    ])
    assert verifier_signaux_utilises(cat, ["lead_bbo"])["ok"] is True
    bad = verifier_signaux_utilises(cat, ["lead_bbo", "invented"])
    assert bad == {"ok": False, "unknown": ["invented"], "reason": "UNKNOWN_SIGNAL_USED"}


def test_aud_263_264_lineage_complet_et_provenance_forte():
    lineage = construire_lineage_ledger(
        source="HL_WS", raw_fingerprint="abc", normalizer="v2", feature="mid",
        signal="lead", intent_id="i1", fill_id="f1", ledger_entry_id="l1",
        provenance="MEASURED",
    )
    assert verifier_provenance_forte(lineage)["ok"] is True
    weak = dict(lineage, provenance="ESTIMATED")
    assert verifier_provenance_forte(weak)["reason"] == "WEAK_PROVENANCE_USED"
    bundle = construire_evidence_bundle(lineage=lineage, payload={"px": 100})
    assert bundle["level"] == "STRONG" and len(bundle["payload_fingerprint"]) == 64


def test_aud_265_266_symbol_master_interdit_unites_implicites():
    master = construire_symbol_master([{
        "venue": "binance", "symbol": "BTCUSDT", "base": "BTC", "quote": "USDT",
        "tick_size": 0.1, "lot_size": 0.001, "contract_multiplier": 1, "quantity_unit": "base",
    }])
    meta = master[("BINANCE", "BTCUSDT")]
    assert calculer_notional_quote(price=50_000, quantity=0.01, metadata=meta) == 500
    with pytest.raises(PreRunInvariantError, match="UNIT_MISMATCH"):
        calculer_notional_quote(price=1, quantity=1, metadata={})


def test_aud_267_268_fee_schedule_versionne_et_cout_total():
    row = valider_fee_schedule({
        "venue": "HL", "version": "2026-08-17", "source": "official",
        "effective_from_ms": 1, "maker_bps": 1.5, "taker_bps": 4.5,
    })
    assert row["taker_bps"] == 4.5
    assert cout_cross_venue_bps(
        entry_fee_bps=4.5, exit_fee_bps=4.5, spread_bps=2, slippage_bps=1,
        transfer_bps=0.5, rebalance_bps=0.5,
    ) == 13.0


def test_aud_269_270_timestamp_unite_explicite_et_drift():
    assert canonicaliser_timestamp_ms(1_000_000, unit="us") == 1000
    with pytest.raises(PreRunInvariantError, match="TIMESTAMP_UNIT_REQUIRED"):
        canonicaliser_timestamp_ms(1_000, unit="auto")
    assert verifier_drift_lead_lag(source_ts_ms=1000, target_ts_ms=1008, max_clock_drift_ms=10)["ok"]
    assert verifier_drift_lead_lag(source_ts_ms=1000, target_ts_ms=1020, max_clock_drift_ms=10)["ok"] is False


def test_aud_271_272_273_normalisation_stale_semantique():
    trade = normaliser_evenement_marche({
        "type": "trade", "venue": "dydx", "symbol": "btc-usd", "ts_ms": 990,
        "price": 100, "size": 1, "side": "buy",
    })
    assert trade["venue"] == "DYDX"
    assert comparer_staleness_intervenue([trade], now_ms=1000, max_age_ms=20)["ok"] is True
    assert lire_prix_semantique({"mark": 100, "last_trade": 101}, semantic="mark") == 100
    with pytest.raises(PreRunInvariantError, match="PRICE_SEMANTIC_MISSING"):
        lire_prix_semantique({"last_trade": 101}, semantic="oracle")


def test_aud_274_278_shadow_replay_contract_et_book_granularity():
    shadow = shadow_record_brut({"venue": "HL", "ts_ms": 2, "sequence": 1, "px": 1})
    assert shadow["raw_fingerprint"]
    events = [
        {"venue": "B", "ts_ms": 2, "sequence": 1},
        {"venue": "A", "ts_ms": 1, "sequence": 1},
    ]
    assert [x["venue"] for x in replay_deterministe(events)] == ["A", "B"]
    assert valider_data_contract({"a": 1}, ["a", "b"])["missing"] == ["b"]
    assert valider_book_granularity({
        "venue": "HL", "depth_levels": 20, "snapshot_interval_ms": 1000, "update_mode": "delta",
    })["ok"] is True


def test_aud_279_280_coinbase_namespace_et_cursor_idempotent():
    assert cle_dedup_coinbase({"product_id": "BTC-USD", "trade_id": "42"}) == ("COINBASE", "BTC-USD", "42")
    assert cle_dedup_coinbase({"product_id": "ETH-USD", "trade_id": "42"}) != ("COINBASE", "BTC-USD", "42")
    assert avancer_cursor_idempotent(current=10, observed=10) == 10
    with pytest.raises(PreRunInvariantError, match="CURSOR_REGRESSION"):
        avancer_cursor_idempotent(current=10, observed=9)


def test_aud_281_282_sqlite_wal_timeout_transaction_et_rollback(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "audit.db")
    policy = configurer_sqlite_strict(db)
    assert policy["journal_mode"] == "wal" and policy["foreign_keys"] == 1
    db.execute("create table t(v integer unique)")
    db.commit()
    transaction_sqlite_atomique(db, [("insert into t(v) values (?)", (1,))])
    with pytest.raises(sqlite3.IntegrityError):
        transaction_sqlite_atomique(db, [
            ("insert into t(v) values (?)", (2,)),
            ("insert into t(v) values (?)", (1,)),
        ])
    assert db.execute("select group_concat(v) from t").fetchone()[0] == "1"


def test_aud_283_285_schema_retention_et_archive():
    assert valider_schema_version({"schema_version": 7}, expected=7)["ok"]
    assert not valider_schema_version({"schema_version": 6}, expected=7)["ok"]
    assert valider_retention_reproductible({
        "keeps_raw": True, "keeps_normalized": True, "keeps_lineage": True, "keeps_schema_version": True,
    })["ok"]
    assert valider_archive_auditable({"raw": 1, "lineage": 2}, ["raw", "lineage"])["ok"]


def test_aud_286_291_run_correlation_logs_health_budget_backpressure():
    rid = str(uuid.uuid4())
    assert nouveau_run_context(rid)["run_id"] == rid
    records = [{"run_id": rid}, {"run_id": rid}, {"run_id": rid}]
    assert verifier_run_id_commun(records)["ok"]
    assert correlation_id(run_id=rid, process="harvester", local_event_id="e1") == correlation_id(
        run_id=rid, process="harvester", local_event_id="e1"
    )
    assert log_structure(level="info", event="heartbeat", run_id=rid, process="dydx")["level"] == "INFO"
    assert agreger_sante_collecteurs({"hl": "GREEN", "dydx": "RED"}, ["hl", "dydx"])["ok"] is False
    assert verifier_budget_ressources({"ram_mb": 50}, {"ram_mb": 100})["ok"]
    assert verifier_backpressure(queue_depth=10, queue_capacity=100, dropped_events=0)["ok"]


def _checkpoint(rid: str, fp: str, boot: str, counter: int = 1):
    return {
        "schema_version": 1,
        "run_id": rid,
        "phase": "SEARCH",
        "family_state": {"COPY_VAULT": {}, "LEAD_LAG": {}, "CROSS_VENUE": {}},
        "search_state": {"sampler": "sobol"},
        "seed": 7,
        "counters": {"trials": counter},
        "data_fingerprint": fp,
        "boot_id": boot,
    }


def test_aud_292_296_checkpoint_complet_autopsie_et_reboot():
    rid = str(uuid.uuid4())
    before = _checkpoint(rid, "fp1", "boot-a", 4)
    after = _checkpoint(rid, "fp1", "boot-b", 5)
    assert valider_checkpoint(before, active_families=["COPY_VAULT", "LEAD_LAG", "CROSS_VENUE"])["ok"]
    assert valider_reprise_checkpoint(before, after)["ok"]
    autopsy = construire_autopsie_incident(
        run_id=rid, process="lab", exception_type="RuntimeError", last_checkpoint="c1", last_event_id="e9"
    )
    assert autopsy["incident_id"]
    assert verifier_reprise_windows(pre_boot_checkpoint=before, post_boot_checkpoint=after)["ok"]


def test_aud_297_298_suspend_resume_et_drift_horloge():
    clean = detecter_discontinuite_alimentation(
        previous_monotonic_ns=0, current_monotonic_ns=1_000_000_000,
        previous_wall_ms=0, current_wall_ms=1000, tolerance_ms=20,
    )
    assert clean["ok"]
    gap = detecter_discontinuite_alimentation(
        previous_monotonic_ns=0, current_monotonic_ns=1_000_000_000,
        previous_wall_ms=0, current_wall_ms=10_000, tolerance_ms=20,
    )
    assert gap["reason"] == "SUSPEND_RESUME_DISCONTINUITY"
    assert verifier_drift_horloge_locale(reference_ms=1000, local_ms=1005, max_abs_drift_ms=10)["ok"]
    assert not verifier_drift_horloge_locale(reference_ms=1000, local_ms=1050, max_abs_drift_ms=10)["ok"]


def test_aud_299_300_atomic_write_ne_laisse_pas_fichier_partiel(tmp_path: Path):
    target = tmp_path / "state.json"
    atomic_write_text(target, '{"version":1}')
    assert target.read_text(encoding="utf-8") == '{"version":1}'
    atomic_write_text(target, '{"version":2}')
    assert target.read_text(encoding="utf-8") == '{"version":2}'
    assert not list(tmp_path.glob(".state.json.*"))
