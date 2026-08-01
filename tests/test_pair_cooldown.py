"""[ARB #26] pair cooldown : après N opportunités disparues avant exécution, suspendre brièvement la paire."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.pair_cooldown import PairCooldown   # noqa: E402


def test_declenche_apres_seuil():
    pc = PairCooldown(seuil_disparitions=3, fenetre_ms=10_000.0, cooldown_ms=30_000.0)
    pc.enregistrer_disparue("BTC/HL-BIN", now_ms=0.0)
    pc.enregistrer_disparue("BTC/HL-BIN", now_ms=1000.0)
    assert pc.en_cooldown("BTC/HL-BIN", now_ms=2000.0)["en_cooldown"] is False
    pc.enregistrer_disparue("BTC/HL-BIN", now_ms=2000.0)          # 3e -> cooldown
    assert pc.en_cooldown("BTC/HL-BIN", now_ms=2500.0)["en_cooldown"] is True


def test_cooldown_expire():
    pc = PairCooldown(seuil_disparitions=1, cooldown_ms=30_000.0)
    pc.enregistrer_disparue("ETH/HL-BIN", now_ms=0.0)
    assert pc.en_cooldown("ETH/HL-BIN", now_ms=40_000.0)["en_cooldown"] is False


def test_hors_fenetre_ne_compte_pas():
    pc = PairCooldown(seuil_disparitions=2, fenetre_ms=1000.0, cooldown_ms=30_000.0)
    pc.enregistrer_disparue("SOL/HL-BIN", now_ms=0.0)
    pc.enregistrer_disparue("SOL/HL-BIN", now_ms=5000.0)         # la 1re est hors fenêtre
    assert pc.en_cooldown("SOL/HL-BIN", now_ms=5000.0)["en_cooldown"] is False
