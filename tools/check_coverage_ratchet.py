"""Gate CI fail-closed pour la couverture de lignes HyperSmart.

Lit un coverage.json produit par coverage.py et compare le pourcentage de lignes
executees a tools/couverture_lignes_baseline.json. Contrairement a
couverture_de_lignes.py, ce gate ne modifie jamais la baseline en CI.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tools" / "couverture_lignes_baseline.json"
COVERAGE = ROOT / "coverage.json"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"COVERAGE_GATE_MISSING: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"COVERAGE_GATE_INVALID: {path}: {exc}") from exc


def main() -> int:
    baseline = _load_json(BASELINE)
    report = _load_json(COVERAGE)

    try:
        minimum = float(baseline["min_pct_lignes"])
        measured = float(report["totals"]["percent_covered"])
        statements = int(report["totals"]["num_statements"])
    except (KeyError, TypeError, ValueError) as exc:
        print(f"COVERAGE_GATE_SCHEMA_INVALID: {exc}")
        return 2

    if statements <= 0:
        print("COVERAGE_GATE_EMPTY: aucune ligne mesuree")
        return 2

    print(f"couverture mesuree={measured:.2f}% baseline={minimum:.2f}% lignes={statements}")
    if measured + 1e-9 < minimum:
        print(
            "COVERAGE_REGRESSION: la couverture de lignes a recule. "
            "La baseline ne doit jamais etre abaissee pour faire passer la CI."
        )
        return 1

    print("COVERAGE_RATCHET_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
