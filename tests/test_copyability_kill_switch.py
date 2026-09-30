"""[pépite 299] copyability kill-switch : suspendre les NOUVELLES entrées quand shortfall > alpha durablement."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.copyability_kill_switch import KillSwitchCopyabilite   # noqa: E402


def test_suspend_apres_breaches_consecutives():
    k = KillSwitchCopyabilite(seuil_consecutif=3)
    assert k.observer(10.0, 5.0)["nouvelles_entrees_suspendues"] is False
    k.observer(10.0, 5.0)
    r = k.observer(10.0, 5.0)                     # 3e brèche
    assert r["nouvelles_entrees_suspendues"] is True and r["gestion_existant_autorisee"] is True


def test_bon_echantillon_reset_le_compteur():
    k = KillSwitchCopyabilite(seuil_consecutif=3)
    k.observer(10.0, 5.0); k.observer(10.0, 5.0)
    r = k.observer(1.0, 5.0)                      # shortfall < alpha -> reset
    assert r["breaches"] == 0 and r["nouvelles_entrees_suspendues"] is False


def test_reset_leve_la_suspension():
    k = KillSwitchCopyabilite(seuil_consecutif=1)
    k.observer(10.0, 5.0)                         # suspendu
    assert k.reset()["nouvelles_entrees_suspendues"] is False
