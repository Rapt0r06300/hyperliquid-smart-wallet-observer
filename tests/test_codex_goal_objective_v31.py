from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBJECTIVE = ROOT / "docs/CODEX_GOAL_OBJECTIVE_V31.txt"


def test_goal_objective_fits_codex_goal_limit_with_margin() -> None:
    text = OBJECTIVE.read_text(encoding="utf-8")
    assert len(text) <= 3600


def test_goal_objective_locks_discovery_local_compute_and_daily_target() -> None:
    text = OBJECTIVE.read_text(encoding="utf-8").casefold()
    assert "mode objectif" in text
    assert "12 hypothèses" in text
    assert "minimum 8" in text
    assert "needs-rediscovery" in text
    assert "needs-challenger" in text
    assert ">=4 challengers" in text
    assert "calcul = local" in text
    assert "codex_quant_batch.py" in text
    assert "cpu-first" in text
    assert "gpu non préféré" in text
    assert "aucun sous-agent" in text
    assert "fast off" in text
    assert "+4.00 usd net/jour" in text
    assert "run_daily_economic_certification.py" in text
