"""Enregistre une suite FULL/COLD seulement après une vraie preuve autonome complète."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.max_data_policy import record_completed_suite_from_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", required=True)
    parser.add_argument("--job-result", required=True)
    args = parser.parse_args(argv)
    try:
        result_path = Path(args.job_result)
        raw = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("JOB_RESULT doit être un objet JSON.")
        if raw.get("analysis_complete") is not True:
            raise ValueError(
                "JOB_RESULT sans analysis_complete=true; les anciens SUCCESS ambigus ou prepare-only sont refusés."
            )
        contract = raw.get("completion_contract")
        if not isinstance(contract, dict) or contract.get("analysis_complete") is not True:
            raise ValueError("Contrat de complétude autonome absent ou incomplet.")
        path = record_completed_suite_from_result(
            Path(args.lab_root),
            result_path,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ALINA_COMPLETED_SUITE_NO_GO: {type(exc).__name__}: {exc}", flush=True)
        return 4
    print(f"ALINA_COMPLETED_SUITE_RECORDED registry={path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
