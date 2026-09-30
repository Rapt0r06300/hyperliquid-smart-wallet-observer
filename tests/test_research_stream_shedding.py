"""[pépite 274] research-stream shedding : en surcharge, lâcher research/télémétrie d'abord, jamais critique."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.capture.research_stream_shedding import decider, CRITIQUE, IMPORTANT, RESEARCH   # noqa: E402

FLUX = [
    {"nom": "bbo", "classe": CRITIQUE},
    {"nom": "exec_state", "classe": CRITIQUE},
    {"nom": "pnl_dashboard", "classe": IMPORTANT},
    {"nom": "telemetry", "classe": RESEARCH},
]


def test_charge_legere_lache_research_seulement():
    r = decider(FLUX, niveau_surcharge=1)
    assert r["abandonnes"] == ["telemetry"] and "bbo" in r["proteges"]


def test_charge_lourde_lache_important_aussi_jamais_critique():
    r = decider(FLUX, niveau_surcharge=2)
    assert set(r["abandonnes"]) == {"telemetry", "pnl_dashboard"}
    assert "bbo" in r["proteges"] and "exec_state" in r["proteges"]


def test_aucune_surcharge_rien_lache():
    assert decider(FLUX, niveau_surcharge=0)["abandonnes"] == []
