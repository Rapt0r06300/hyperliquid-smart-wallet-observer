"""[MEMOIRE item 6] Budget RAM automatique et BORNE : un plafond <= 0 ne charge JAMAIS tout, il
calcule un budget borne [mini, maxi] a partir de la RAM disponible. Injectable -> 0 reseau, deterministe.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import budget_ram as B                # noqa: E402


class _FauxPsutil:
    def __init__(self, dispo_octets):
        self._d = dispo_octets

    def virtual_memory(self):
        class V:
            available = self._d
        return V()


def test_budget_borne_entre_mini_et_maxi():
    # peu de RAM -> plancher mini (jamais 0).
    assert B.budget_events(dispo_octets=1024) == B.MINI_EVENTS
    # enormement de RAM -> plafond maxi (jamais illimite).
    assert B.budget_events(dispo_octets=10**15) == B.MAXI_EVENTS
    # cas intermediaire : fraction de la RAM / octets_par_event.
    n = B.budget_events(dispo_octets=8 * 1024**3, octets_par_event=1024, fraction=0.25)
    assert B.MINI_EVENTS <= n <= B.MAXI_EVENTS and n == int(8 * 1024**3 * 0.25 / 1024)


def test_resoudre_zero_donne_budget_auto_jamais_illimite():
    n = B.resoudre_max_events(0, dispo_octets=8 * 1024**3)
    assert n > 0 and n <= B.MAXI_EVENTS                      # 0 => auto borne, jamais 0/illimite
    assert B.resoudre_max_events(-1, dispo_octets=1024) == B.MINI_EVENTS


def test_resoudre_plafond_explicite_respecte_mais_borne():
    assert B.resoudre_max_events(123_456, dispo_octets=8 * 1024**3) == 123_456   # explicite respecte
    assert B.resoudre_max_events(10**9) == B.MAXI_EVENTS     # meme explicite est borne par maxi


def test_memoire_disponible_via_psutil_injecte():
    assert B.memoire_disponible_octets(psutil_mod=_FauxPsutil(4 * 1024**3)) == 4 * 1024**3
    # psutil absent/casse -> defaut conservateur, jamais 0.
    assert B.memoire_disponible_octets(psutil_mod=_FauxPsutil(0)) == B.DEFAUT_RAM_DISPO_MO * 1024 * 1024


def test_lab_alpha_utilise_le_budget_borne():
    # cablage : lab_alpha resout un budget borne, ne passe plus max_ram=0 illimite.
    import inspect
    from hl_observer.ops import lab_alpha as LA
    src = inspect.getsource(LA)
    assert "resoudre_max_events(" in src and "budget_ram_events" in src
    assert "max_ram=(min(plafond) if plafond else 0)" not in src   # l'ancien defaut illimite est parti
