"""[COPY-VAULT lot2 #65] heartbeat/liveness par vault : indépendant du heartbeat général du bot."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.vault_heartbeat import HeartbeatVaults   # noqa: E402


def test_vivant_apres_battement():
    h = HeartbeatVaults(timeout_ms=30_000.0)
    h.battement("vaultA", now_ms=1000.0)
    assert h.vivant("vaultA", now_ms=5000.0)["vivant"] is True


def test_silencieux_mort():
    h = HeartbeatVaults(timeout_ms=30_000.0)
    h.battement("vaultA", now_ms=1000.0)
    assert h.vivant("vaultA", now_ms=50_000.0)["vivant"] is False


def test_jamais_vu_mort():
    assert HeartbeatVaults().vivant("vaultB", now_ms=1000.0)["vivant"] is False   # indépendant par vault
