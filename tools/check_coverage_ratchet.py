"""Gate CI fail-closed pour la couverture de lignes HyperSmart.

Lit un coverage.json produit par coverage.py et compare la couverture réelle à
la baseline versionnée. À 100 %, une seule ligne manquante suffit à faire échouer
la gate, même si un affichage arrondi pouvait montrer 100,00 %.
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
        max_missing = int(baseline.get("max_missing_lines", 0 if minimum >= 100.0 else 2**31 - 1))
        totals = report["totals"]
        measured = float(totals["percent_covered"])
        statements = int(totals["num_statements"])
        missing = int(totals.get("missing_lines", 0))
    except (KeyError, TypeError, ValueError) as exc:
        print(f"COVERAGE_GATE_SCHEMA_INVALID: {exc}")
        return 2

    if statements <= 0:
        print("COVERAGE_GATE_EMPTY: aucune ligne mesuree")
        return 2
    if missing < 0 or missing > statements:
        print(f"COVERAGE_GATE_SCHEMA_INVALID: missing_lines={missing} statements={statements}")
        return 2

    print(
        f"couverture mesuree={measured:.6f}% baseline={minimum:.6f}% "
        f"lignes={statements} manquantes={missing} max_manquantes={max_missing}"
    )

    if measured + 1e-12 < minimum:
        print(
            "COVERAGE_REGRESSION: la couverture de lignes est sous la cible. "
            "La baseline ne doit jamais etre abaissee pour faire passer la CI."
        )
        return 1

    if missing > max_missing:
        print(
            "COVERAGE_MISSING_LINES: la cible exige zero ligne manquante. "
            "Ajouter des tests reels; ne pas exclure artificiellement le code."
        )
        return 1

    if minimum >= 100.0 and (measured < 100.0 or missing != 0):
        print("COVERAGE_100_NOT_PROVEN: 100% exact et 0 ligne manquante sont obligatoires")
        return 1

    print("COVERAGE_RATCHET_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
