"""[COPY-VAULT lot2 #61] monotonic-state rule : un snapshot plus ancien ne peut écraser un état plus récent."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.monotonic_state_rule import decision, APPLIQUER, IGNORER   # noqa: E402


def test_plus_recent_applique():
    r = decision(version_courante=5, version_entrante=6)
    assert r["action"] == APPLIQUER and r["nouvelle_version"] == 6


def test_retarde_ignore():
    r = decision(version_courante=6, version_entrante=5)  # REST retardé, snapshot plus vieux
    assert r["action"] == IGNORER and r["raison"] == "SNAPSHOT_PLUS_ANCIEN_OU_EGAL"


def test_egal_ignore():
    assert decision(version_courante=6, version_entrante=6)["action"] == IGNORER
