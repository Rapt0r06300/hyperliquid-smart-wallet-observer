"""Enregistre une suite FULL/COLD seulement après un vrai JOB_RESULT autonome réussi."""
from __future__ import annotations

import argparse
from pathlib import Path

from hl_observer.datasets.max_data_policy import record_completed_suite_from_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", required=True)
    parser.add_argument("--job-result", required=True)
    args = parser.parse_args(argv)
    try:
        path = record_completed_suite_from_result(
            Path(args.lab_root),
            Path(args.job_result),
        )
    except (OSError, ValueError) as exc:
        print(f"ALINA_COMPLETED_SUITE_NO_GO: {type(exc).__name__}: {exc}", flush=True)
        return 4
    print(f"ALINA_COMPLETED_SUITE_RECORDED registry={path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
