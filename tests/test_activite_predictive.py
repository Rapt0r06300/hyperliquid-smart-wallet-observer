"""Tests de l'intelligence prédictive d'activité (#82-90)."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import activite_predictive as A  # noqa: E402

NOW = 1_800_000_000_000
M = 60_000


def test_debit_ewma_recent_pese_plus():
    recent = A.debit_ewma([NOW - 1 * M, NOW - 2 * M], now_ms=NOW)
    vieux = A.debit_ewma([NOW - 60 * M, NOW - 61 * M], now_ms=NOW)
    assert recent > vieux > 0
    assert A.debit_ewma([], now_ms=NOW) == 0.0


def test_profil_et_facteur_horaire():
    # 10 fills bien au cœur d'une heure H (pas à cheval sur une frontière)
    base = (NOW // 3_600_000) * 3_600_000 + 100_000   # 100 s après le début de l'heure
    h = int((base // 3_600_000) % 24)
    ts = [base + i * 1000 for i in range(10)]
    prof = A.profil_horaire(ts)
    assert prof.get(h) == 10
    assert A.facteur_horaire(prof, h) > 1.0


def test_momentum_detecte_acceleration():
    # beaucoup de fills récents, aucun ancien → momentum > 1
    ts = [NOW - i * 1000 for i in range(20)]
    assert A.momentum(ts, now_ms=NOW) > 1.0


def test_classer_leaders_tri():
    hist = {
        "0xactif": [NOW - i * 1000 for i in range(30)],
        "0xcalme": [NOW - 120 * M],
        "0xvide": [],
    }
    rang = A.classer_leaders(hist, now_ms=NOW)
    assert rang[0][0] == "0xactif"
    assert rang[-1][1] == 0.0        # le vide prédit 0
    assert [l for l, _ in rang][:1] == ["0xactif"]
