"""[COPY-VAULT #68] post-fill source confirmation : le snapshot du leader doit confirmer le delta reconstruit."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.post_fill_source_confirmation import confirmer   # noqa: E402


def test_snapshot_confirme():
    r = confirmer(2.0, 1.5, 3.5)                              # 2 + 1.5 == 3.5
    assert r["confirme"] is True and r["ecart"] == 0.0


def test_snapshot_contredit():
    r = confirmer(2.0, 1.5, 5.0)                              # 3.5 attendu != 5.0
    assert r["confirme"] is False and r["raison"] == "SNAPSHOT_CONTREDIT_DELTA"


def test_donnee_manquante():
    assert confirmer(2.0, None, 3.5)["confirme"] is False
