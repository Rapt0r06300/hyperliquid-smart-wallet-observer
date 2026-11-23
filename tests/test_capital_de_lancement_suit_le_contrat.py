"""Le capital de départ de CHAQUE lanceur et de chaque défaut suit la source unique `PAPER_EQUITY_USD`.

23/11/2026 : le contrat est passé de 350 à 100 USD le 18/11, mais le même capital existait encore sous TROIS
valeurs actives : 350 dans `LANCER_HYPERSMART.cmd`, 350 et 200 dans `start_hypersmart_simulation.ps1`, 350 dans
`runtime_flags` et le `cli`. Le moteur de simulation tournait donc sur 350 USD sous un contrat de 100.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.contrat_paper import PAPER_EQUITY_USD  # noqa: E402


def _valeurs(chemin: str, motif: str) -> list[float]:
    texte = (RACINE / chemin).read_text(encoding="utf-8-sig", errors="replace")
    return [float(v) for v in re.findall(motif, texte)]


def test_le_lanceur_cmd_suit_le_contrat() -> None:
    vals = _valeurs("LANCER_HYPERSMART.cmd", r'set "HYPERSMART_SIMULATION_INITIAL_EQUITY_USDT=([0-9.]+)"')
    assert vals and all(v == PAPER_EQUITY_USD for v in vals), vals


def test_le_script_powershell_suit_le_contrat_y_compris_sa_valeur_de_secours() -> None:
    defaut = _valeurs("tools/start_hypersmart_simulation.ps1",
                      r'Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_INITIAL_EQUITY_USDT" "([0-9.]+)"')
    secours = _valeurs("tools/start_hypersmart_simulation.ps1", r'\$paperStartingEquity = "([0-9.]+)"')
    assert defaut and secours and all(v == PAPER_EQUITY_USD for v in defaut + secours), (defaut, secours)


def test_les_defauts_python_suivent_le_contrat(monkeypatch) -> None:
    monkeypatch.delenv("HYPERSMART_SIMULATION_INITIAL_EQUITY_USDT", raising=False)
    from hl_observer.config.runtime_flags import load_sizing

    assert load_sizing().capital_usd == PAPER_EQUITY_USD
    cli = (RACINE / "src/hl_observer/cli.py").read_text(encoding="utf-8")
    assert "350.0" not in cli and "starting_equity_usdt=350" not in cli
