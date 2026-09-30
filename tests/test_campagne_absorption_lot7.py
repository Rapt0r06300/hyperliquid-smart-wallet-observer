"""LOT 7 — campagne ABSORPTION : détecteur pur + campagne prouvés sans réseau (Flo 25/07)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("mca", _ROOT / "tools" / "mesurer_campagne_absorption.py")
MCA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MCA)


def test_detecteur_absorption_pre_enregistre():
    # ≥10 buckets calmes (petit flux) puis un événement : gros flux one-sided, prix immobile
    rows = [(i * 5000.0, 100.0, 100.01, 5.0, 50.0) for i in range(12)]          # bruit de fond
    rows.append((12 * 5000.0, 100.0, 100.01, 900.0, 1000.0))                    # |net|/gross=0.9, gross>>med, prix plat
    ev = MCA.detecter_absorption(rows)
    assert len(ev) == 1 and ev[0]["signe"] == 1, "flux acheteur massif absorbé -> 1 événement, signe +"


def test_pas_d_absorption_si_le_prix_bouge():
    rows = [(i * 5000.0, 100.0, 100.01, 5.0, 50.0) for i in range(12)]
    rows.append((12 * 5000.0, 101.0, 101.01, 900.0, 1000.0))                    # prix a bougé ~100 bps
    assert MCA.detecter_absorption(rows) == [], "si le prix se déplace, ce n'est pas de l'absorption"


def test_pas_d_absorption_si_flux_equilibre():
    rows = [(i * 5000.0, 100.0, 100.01, 5.0, 50.0) for i in range(12)]
    rows.append((12 * 5000.0, 100.0, 100.01, 50.0, 1000.0))                     # |net|/gross=0.05 -> équilibré
    assert MCA.detecter_absorption(rows) == []


def test_campagne_rend_markouts_et_decision():
    # série synthétique : événement d'absorption + prix plat après -> net ~ coûts -> KILL
    rows = [(i * 5000.0, 100.0, 100.01, 5.0, 50.0) for i in range(6)]
    rows += [(6 * 5000.0, 100.0, 100.01, 900.0, 1000.0)]
    rows += [(i * 5000.0, 100.0, 100.01, 5.0, 50.0) for i in range(7, 40)]      # plat ensuite
    rap = MCA.campagne({"AAA": rows * 1})
    assert rap["n_evenements"] >= 1
    assert "ABSORPTION_REVERSAL" in rap["variantes"] and "ABSORPTION_CONTINUATION" in rap["variantes"]
