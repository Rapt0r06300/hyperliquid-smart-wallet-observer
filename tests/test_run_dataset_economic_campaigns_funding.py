from __future__ import annotations

from pathlib import Path

from tools import run_dataset_economic_campaigns as runner


def test_dataset_runner_charge_funding_coffre_sur_la_fenetre_v21(
    tmp_path: Path, monkeypatch
) -> None:
    expected_rates = {"BTC": [(3_600_000, "0.0001")]}
    calls: list[dict[str, object]] = []

    def load_rates(root, *, coins, debut_ms, fin_ms):
        calls.append(
            {
                "root": root,
                "coins": coins,
                "debut_ms": debut_ms,
                "fin_ms": fin_ms,
            }
        )
        return expected_rates, {
            "status": "LU_DEPUIS_LE_COFFRE",
            "reglements_gardes": 1,
            "shards_lus": 1,
            "economic_proof_allowed": False,
            "economic_proof_block_reason": "SETTLEMENT_ORACLE_PRICE_NOT_JOINED",
            "evidence_admission": "SAFE_REPLAY_ADMISSIBLE",
        }

    monkeypatch.setattr(runner._FUNDING_REEL, "taux_du_coffre", load_rates)

    rates, audit = runner._load_copy_v21_funding(
        tmp_path,
        [{"coin": "BTC"}],
        {"BTC": [{"ts_ms": 1_000}, {"ts_ms": 2_000}]},
        {
            "freeze": {
                "frozen_at_ms": 500,
                "parameters": {"bounds": {"validation_start_ms": 100}},
            }
        },
    )

    assert rates is expected_rates
    assert calls == [
        {
            "root": tmp_path,
            "coins": ["BTC"],
            "debut_ms": 100,
            "fin_ms": 2_000,
        }
    ]
    assert audit["dataset_family"] == "funding_history"
    assert audit["requested_start_ms"] == 100
    assert audit["requested_end_ms"] == 2_000
    assert audit["all_selected_shards_sha256_verified"] is True
    assert audit["economic_proof_allowed"] is False
    assert audit["economic_proof_block_reason"] == "SETTLEMENT_ORACLE_PRICE_NOT_JOINED"
    assert audit["paper_read_only"] is True


def test_dataset_runner_refuse_une_fenetre_funding_sans_bornes_valides(
    tmp_path: Path, monkeypatch
) -> None:
    def fail_if_read(*_args, **_kwargs):
        raise AssertionError("must fail closed before reading funding data")

    monkeypatch.setattr(runner._FUNDING_REEL, "taux_du_coffre", fail_if_read)

    rates, audit = runner._load_copy_v21_funding(
        tmp_path,
        [{"coin": "BTC"}],
        {"BTC": [{"ts_ms": 2_000}]},
        {"freeze": {"parameters": {"bounds": {"validation_start_ms": True}}}},
    )

    assert rates is None
    assert audit == {
        "status": "FREEZE_BOUNDS_UNMEASURABLE",
        "economic_proof_allowed": False,
    }


def test_dataset_runner_preserves_local_certified_funding_as_exploratory_only(
    tmp_path: Path, monkeypatch
) -> None:
    expected_rates = {"BTC": [(3_600_000, "0.0001")]}
    monkeypatch.setattr(
        runner._FUNDING_REEL,
        "taux_du_coffre",
        lambda *_args, **_kwargs: (
            expected_rates,
            {
                "status": "LU_DEPUIS_LE_COFFRE",
                "evidence_admission": "LOCAL_CERTIFIED_EXPLORATORY_ONLY",
                "economic_proof_allowed": False,
            },
        ),
    )

    rates, audit = runner._load_copy_v21_funding(
        tmp_path,
        [{"coin": "BTC"}],
        {"BTC": [{"ts_ms": 2_000}]},
        {
            "freeze": {
                "frozen_at_ms": 500,
                "parameters": {"bounds": {"validation_start_ms": 100}},
            }
        },
    )

    assert rates is expected_rates
    assert audit["evidence_admission"] == "LOCAL_CERTIFIED_EXPLORATORY_ONLY"
    assert audit["economic_proof_allowed"] is False
