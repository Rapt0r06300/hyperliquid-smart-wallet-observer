"""[COPY-VAULT lot2 #64] leader operational-quality : pénalité distincte du PnL (erreurs, reconnects, etc.)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.leader_operational_quality import score   # noqa: E402


def test_parfait():
    r = score(erreurs=0, reconnects=0, etats_incoherents=0, cadence_extreme=False, donnees_absentes=0)
    assert r["operational_quality"] == 1.0 and r["distinct_du_pnl"] is True


def test_penalise():
    r = score(erreurs=2, reconnects=1, etats_incoherents=1, cadence_extreme=True, donnees_absentes=0)
    assert r["operational_quality"] < 1.0 and "erreurs" in r["penalites"] and "cadence_extreme" in r["penalites"]


def test_borne_a_zero():
    r = score(erreurs=10, reconnects=10, etats_incoherents=10, cadence_extreme=True, donnees_absentes=10)
    assert r["operational_quality"] == 0.0
