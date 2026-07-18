"""Palier de frais — plus de volume = frais plus bas ; volume inconnu = palier de base (jamais mieux)."""
from __future__ import annotations

from hl_observer.fees.fee_tier import economie_bps_2_jambes, frais_selon_volume


def test_palier_selon_volume():
    assert frais_selon_volume(None) == (1.5, 4.5)          # inconnu -> base (le plus cher)
    assert frais_selon_volume(1_000_000.0) == (1.5, 4.5)
    assert frais_selon_volume(10_000_000.0) == (1.2, 4.0)
    assert frais_selon_volume(30_000_000.0) == (1.0, 3.5)


def test_economie_croit_avec_le_volume():
    assert economie_bps_2_jambes(None) == 0.0              # base -> pas d'économie
    assert economie_bps_2_jambes(30_000_000.0, maker=True) == 1.0   # 2×(1.5-1.0)
    assert economie_bps_2_jambes(30_000_000.0) > economie_bps_2_jambes(10_000_000.0)
