"""Legacy 2100-item milestone plus canonical 3120-task coverage. Offline only."""
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
PROGRESS = runpy.run_path(str(ROOT / "tools/roadmap_722_progress.py"))
BASE = ROOT / "docs/superpowers/plans/2026-11-02-alina-audit-roadmap-190.md"
HVR = ROOT / "docs/superpowers/plans/2026-11-02-alina-audit-roadmap-190-hvr-1000.md"
LEGACY_COUNTS = {k: v for k, v in PROGRESS["EXPECTED"].items() if k not in {"ASF-HVR-INT", "ASF-RIG"}}


def test_canonical_2100_integrity():
    source = BASE.read_text(encoding="utf-8") + "\n" + HVR.read_text(encoding="utf-8")
    result = PROGRESS["inspect_roadmap"](source, expected=LEGACY_COUNTS)
    assert result["present"] == result["total"] == 2100
    assert result["groups"]["HVR"]["total"] == 1000
    assert not result["errors"], result["errors"][:20]


def test_hvr_sequence_and_initial_evidence_state():
    lines = HVR.read_text(encoding="utf-8").splitlines()
    matches = [i for i, line in enumerate(lines) if line.startswith("- [ ] **[HVR-")]
    assert len(matches) == 1000
    for n, i in enumerate(matches, 1):
        assert lines[i].startswith(f"- [ ] **[HVR-{n:04d}]")
        assert "**Suivi Codex :** `TODO`" in lines[i + 1]
        assert "**Reçu de clôture :** `PENDING`" in lines[i + 1]


def test_hvr_falsification_never_implies_done():
    source = BASE.read_text(encoding="utf-8") + "\n" + HVR.read_text(encoding="utf-8")
    result = PROGRESS["inspect_roadmap"](source, expected=LEGACY_COUNTS)
    assert result["groups"]["HVR"]["verified"] == 0
