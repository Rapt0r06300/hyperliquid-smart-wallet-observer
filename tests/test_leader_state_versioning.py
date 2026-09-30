"""[COPY-VAULT lot2 #41] leader-state versioning : chaque snapshot equity+positions reçoit une version immuable."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.leader_state_versioning import VersionneurEtat   # noqa: E402


def test_versions_monotones():
    v = VersionneurEtat()
    s1 = v.nouveau_snapshot(equity=1000.0, positions={"BTC": 0.5})
    s2 = v.nouveau_snapshot(equity=1010.0, positions={"BTC": 0.6})
    assert s1["version"] == 1 and s2["version"] == 2 and v.version_courante() == 2


def test_snapshot_immuable():
    v = VersionneurEtat()
    s1 = v.nouveau_snapshot(equity=1000.0, positions={"BTC": 0.5})
    s1["positions"]["BTC"] = 999                         # mutation de la copie...
    assert v.obtenir(1)["positions"]["BTC"] == 0.5       # ...n'affecte pas le stock


def test_version_inconnue():
    assert VersionneurEtat().obtenir(5) is None
