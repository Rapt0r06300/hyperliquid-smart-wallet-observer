from __future__ import annotations

from pathlib import Path

from hl_observer.research.kronos_context_contract import (
    build_context_receipt,
    preregister_comparison,
    summarize_forecast_rows,
)


def _metadata() -> dict:
    return {
        "repository": "vendor/kronos",
        "article": "doi:example",
        "model": "kronos-v1",
        "license": "Apache-2.0",
        "dependencies": {"python": "3.12", "numpy": "2.0"},
        "training_cutoff": "2026-01-01T00:00:00Z",
        "parameters": {"horizon": 60, "seed": 7},
    }


def test_context_receipt_hashes_metadata_and_source_files(tmp_path: Path) -> None:
    source = tmp_path / "model.json"
    source.write_text('{"model":"kronos-v1"}\n', encoding="utf-8")

    receipt = build_context_receipt(_metadata(), source_files={"model": source})

    assert receipt["status"] == "READY"
    assert receipt["missing_evidence"] == []
    assert len(receipt["source_file_sha256"]["model"]) == 64
    assert len(receipt["receipt_sha256"]) == 64
    assert receipt["paper_read_only"] is True
    assert receipt["real_execution"] is False


def test_context_receipt_is_unmeasurable_when_provenance_is_missing() -> None:
    metadata = _metadata()
    metadata.pop("license")

    receipt = build_context_receipt(metadata)

    assert receipt["status"] == "UNMEASURABLE"
    assert receipt["missing_evidence"] == ["license"]


def test_forecast_summary_uses_observed_sample_count_and_mean() -> None:
    result = summarize_forecast_rows([
        {"forecast_error": "1.0"},
        {"forecast_error": "3.0"},
    ])

    assert result == {
        "status": "MEASURED",
        "reason": None,
        "sample_count": 2,
        "mean": "2.0",
    }


def test_forecast_summary_refuses_empty_or_missing_values() -> None:
    assert summarize_forecast_rows([])["reason"] == "FORECAST_SAMPLE_EMPTY"
    assert summarize_forecast_rows([{}])["reason"] == "FORECAST_VALUE_MISSING"
    assert summarize_forecast_rows([{"forecast_error": "nan"}])["reason"] == "FORECAST_VALUE_INVALID"


def test_preregistered_comparison_forbids_oos_and_forward_retuning() -> None:
    result = preregister_comparison(
        train_window={"start_ms": 10, "end_ms": 20},
        conditions=("without_kronos", "with_kronos"),
        baselines=("copy_vault_current",),
        seed=7,
    )

    assert result["status"] == "PREREGISTERED"
    assert result["oos_tuning_allowed"] is False
    assert result["forward_tuning_allowed"] is False
    assert len(result["protocol_sha256"]) == 64


def test_preregistered_comparison_fails_closed_on_forbidden_tuning() -> None:
    result = preregister_comparison(
        train_window={"start_ms": 10, "end_ms": 20},
        conditions=("without_kronos", "with_kronos"),
        baselines=("copy_vault_current",),
        seed=7,
        oos_tuning_allowed=True,
    )

    assert result["status"] == "UNMEASURABLE"
    assert result["reasons"] == ["OOS_TUNING_FORBIDDEN"]
