"""H23/H24 : un effet planté est détecté, l'absence d'effet est rejetée (statistique et placebo)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import goal2_hlp_timing as T  # noqa: E402


def test_effet_plante_detecte_et_absence_rejetee() -> None:
    rng = np.random.default_rng(1)
    x = rng.uniform(0, 1, 60)
    avec = pd.DataFrame({"ind": x, "rendement_bps": 50 * x + rng.normal(0, 3, 60)})
    sans = pd.DataFrame({"ind": x, "rendement_bps": rng.normal(0, 10, 60)})
    assert T.tester(avec, "ind")["statut"] == "CANDIDAT_PROSPECTIF"
    assert T.tester(sans, "ind")["statut"] == "REJECTED"


def test_les_horodatages_ironflow_sont_en_millisecondes() -> None:
    if not list((T.IRON / "liquidations" / "data" / "events").glob("*.parquet")) or not list(
        (T.IRON / "funding" / "data").glob("*.parquet")
    ):
        pytest.skip("corpus Ironflow externe absent du runner; preuve de timing UNMEASURABLE")
    liq = T._iron("liquidations", ["timestamp", "market", "notional_usd"], "events")
    fun = T._iron("funding", ["timestamp", "dex", "funding_rate"])
    for d in (liq, fun):
        assert 1.6e12 < d["t_ms"].min() < d["t_ms"].max() < 1.9e12      # 2020 < t < 2030, en ms
