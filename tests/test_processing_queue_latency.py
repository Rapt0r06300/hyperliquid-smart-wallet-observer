"""[COPY-VAULT lot2 #45] queue de traitement : latence fill_received -> copy_decision, pas juste le réseau."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.processing_queue_latency import latence_traitement_ms   # noqa: E402


def test_latence_interne():
    r = latence_traitement_ms(1000.0, 1250.0)
    assert r["latence_ms"] == 250.0 and r["composante"] == "queue_cpu_interne"


def test_decision_avant_reception_non_mesurable():
    assert latence_traitement_ms(2000.0, 1000.0)["latence_ms"] == "UNMEASURABLE"


def test_horodatage_invalide():
    assert latence_traitement_ms(None, 1000.0)["latence_ms"] == "UNMEASURABLE"
