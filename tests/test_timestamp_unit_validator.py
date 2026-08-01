"""[pépite 256] timestamp-unit validator : détecter la confusion s/ms/µs/ns avant de classer un signal frais."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.data_contract.timestamp_unit_validator import detecter_unite, valider   # noqa: E402


def test_detection_unite():
    assert detecter_unite(1_700_000_000) == "s"
    assert detecter_unite(1_700_000_000_000) == "ms"
    assert detecter_unite(1_700_000_000_000_000) == "us"


def test_validation_conforme_et_non():
    assert valider(1_700_000_000_000, unite_attendue="ms")["conforme"] is True
    r = valider(1_700_000_000, unite_attendue="ms")          # secondes fournies, ms attendu
    assert r["conforme"] is False and r["unite_detectee"] == "s"


def test_hors_plage_fail_closed():
    r = valider(12345, unite_attendue="ms")
    assert r["conforme"] is False and r["unite_detectee"] == "INCONNU"
