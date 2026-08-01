"""[COPY-VAULT #69] leader-state TTL : equity et positions ont chacune leur âge maximal ; périmé -> invalide."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.leader_state_ttl import etat_valide   # noqa: E402


def test_les_deux_frais():
    r = etat_valide(age_equity_ms=500.0, age_positions_ms=800.0, ttl_equity_ms=1000.0, ttl_positions_ms=1000.0)
    assert r["valide"] is True


def test_positions_perimees_invalide_tout():
    r = etat_valide(age_equity_ms=500.0, age_positions_ms=2000.0, ttl_equity_ms=1000.0, ttl_positions_ms=1000.0)
    assert r["valide"] is False and "positions" in r["perimes"]


def test_age_inconnu_invalide():
    r = etat_valide(age_equity_ms=None, age_positions_ms=800.0, ttl_equity_ms=1000.0, ttl_positions_ms=1000.0)
    assert r["valide"] is False and "equity" in r["perimes"]
