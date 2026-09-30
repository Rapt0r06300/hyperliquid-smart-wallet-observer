"""[COPY-VAULT lot2 #48] SLA par vault : p50/p95/p99 de leader fill -> PaperIntent."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.per_vault_sla import SLAVault   # noqa: E402


def test_percentiles():
    s = SLAVault()
    for v in [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]:
        s.enregistrer("vaultA", v)
    r = s.sla("vaultA", min_echantillons=5)
    assert r["p50"] <= r["p95"] <= r["p99"] and r["n"] == 10


def test_echantillon_insuffisant():
    s = SLAVault()
    s.enregistrer("vaultA", 10.0)
    assert s.sla("vaultA", min_echantillons=5)["p50"] == "UNMEASURABLE"


def test_latence_invalide_refusee():
    s = SLAVault()
    assert s.enregistrer("vaultA", -1.0) is False
