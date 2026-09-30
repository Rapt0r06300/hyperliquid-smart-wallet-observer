"""[COPY-VAULT #55] leader leverage ceiling : notional copié borné a levier_max x notre_equity."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.leader_leverage_ceiling import notional_admissible   # noqa: E402


def test_cap_levier():
    r = notional_admissible(50000.0, notre_equity=5000.0, levier_max=5.0)
    assert r["notional"] == 25000.0 and r["capee"] is True   # 5000*5 = 25000, levier demandé 10x
    assert r["levier_demande"] == 10.0


def test_sous_le_cap_inchange():
    r = notional_admissible(20000.0, notre_equity=5000.0, levier_max=5.0)
    assert r["notional"] == 20000.0 and r["capee"] is False


def test_equity_non_positive_refuse():
    assert notional_admissible(20000.0, notre_equity=0.0, levier_max=5.0)["refuse"] is True
