"""[ALL #94] safe read retry : backoff+jitter pour LECTURES ; jamais de retry aveugle sur soumission inconnue."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core import safe_read_retry as SRR   # noqa: E402


def test_backoff_croissant_et_deterministe():
    d1 = SRR.delais_backoff(4, base_ms=100.0, max_ms=5000.0, jitter_frac=0.0, seed=7)
    assert d1 == [100.0, 200.0, 400.0, 800.0]            # exponentiel, jitter 0
    # jitter déterministe : même seed -> même suite
    assert SRR.delais_backoff(3, seed=42) == SRR.delais_backoff(3, seed=42)


def test_lecture_retry_sous_plafond():
    assert SRR.peut_retry(SRR.LECTURE, tentative=1, max_retries=3)["retry"] is True
    assert SRR.peut_retry(SRR.LECTURE, tentative=3, max_retries=3)["retry"] is False


def test_soumission_etat_inconnu_pas_de_retry():
    r = SRR.peut_retry(SRR.SOUMISSION, tentative=0, max_retries=3, etat_connu=False)
    assert r["retry"] is False and r["raison"] == "SOUMISSION_ETAT_INCONNU_RECONCILIER"
