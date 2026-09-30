"""[pépite 281] source execution-style profile : taux maker/taker, partial fills → caractéristiques de copyabilité."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.source_execution_style_profile import profiler   # noqa: E402


def test_profil_maker_dominant():
    fills = [{"is_maker": True}, {"is_maker": True}, {"is_maker": True}, {"is_maker": False}]
    p = profiler(fills)
    assert p["taux_maker"] == 0.75 and p["taux_taker"] == 0.25 and p["n"] == 4


def test_part_partial():
    fills = [{"crossed": True, "partial": True}, {"crossed": True}]
    assert profiler(fills)["part_partial"] == 0.5


def test_aucun_fill():
    assert profiler([])["profil"] == "UNMEASURABLE"
