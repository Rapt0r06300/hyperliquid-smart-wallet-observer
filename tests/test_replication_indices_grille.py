"""Réplication paper : prix du pas lus à l'indice de grille (25/11/2026) -- résultats IDENTIQUES à l'ancienne voie.

Profil réel : 1,26 M appels à ``at_one`` = la moitié du temps de ``run_replication`` ; chacun refaisait un
``searchsorted`` déjà fait pour la grille. Ce test compare la nouvelle voie (``INDICES_DE_GRILLE = True``) à
l'ancienne sur des portefeuilles et des panneaux tirés au hasard : prix manquants, trous de fraîcheur, coins sans
prix, funding partiel, décalage placebo.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_replication_paper as R  # noqa: E402
from hl_observer.backtesting.copy_vault_copiability_entrees import PricePanel  # noqa: E402

DEBUT = 1_794_000_000_000
H = 3_600_000


def _monde(graine: int):
    rng = np.random.default_rng(graine)
    n = int(rng.integers(400, 1500))
    ts = DEBUT + np.cumsum(rng.integers(30_000, 400_000, n)).astype(np.int64)
    coins = ("BTC", "ETH", "SOL", "DOGE")
    px = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.003, (n, len(coins))), axis=0))
    px[rng.random((n, len(coins))) < 0.1] = np.nan
    panel = PricePanel(ts=ts, px=px, coins=coins, provenance="TEST", stale_ms=int(rng.integers(120_000, 900_000)))
    portefeuille = []
    t = int(ts[0]) - int(rng.integers(0, 2 * H))
    while t < int(ts[-1]):
        tailles = {c: float(rng.normal(0, 3)) for c in rng.choice(coins + ("INCONNU",), size=int(rng.integers(0, 4)),
                                                                   replace=False)}
        nav = float(rng.uniform(5_000, 50_000)) if rng.random() > 0.05 else None
        portefeuille.append((t, nav, tailles))
        t += int(rng.integers(60_000, 2 * H))
    spreads = {c: float(rng.uniform(0.5, 6)) for c in coins if rng.random() < 0.8}
    funding = {c: np.where(rng.random(n) < 0.2, np.nan, rng.normal(0, 1e-5, n)) for c in coins if rng.random() < 0.7}
    return panel, portefeuille, spreads, funding


def _deux_voies(monkeypatch, fonction, *args, **kwargs):
    monkeypatch.setattr(R, "INDICES_DE_GRILLE", True)
    neuf = fonction(*args, **kwargs)
    monkeypatch.setattr(R, "INDICES_DE_GRILLE", False)
    ancien = fonction(*args, **kwargs)
    return neuf, ancien


@pytest.mark.parametrize("graine", range(16))
def test_run_replication_rend_exactement_l_ancienne_voie(graine, monkeypatch):
    panel, portefeuille, spreads, funding = _monde(graine)
    neuf, ancien = _deux_voies(monkeypatch, R.run_replication, portefeuille, panel, spreads, R.ReplicationConfig(),
                               funding_rates=funding)
    assert neuf == ancien                                        # égalité stricte de tout le bilan
    decale = [(t + 24 * H, nav, tailles) for t, nav, tailles in portefeuille]   # placebo
    neuf, ancien = _deux_voies(monkeypatch, R.run_replication, decale, panel, spreads, R.ReplicationConfig(),
                               funding_rates=funding)
    assert neuf == ancien


@pytest.mark.parametrize("graine", range(6))
def test_decomposer_les_pertes_rend_exactement_l_ancienne_voie(graine, monkeypatch):
    panel, portefeuille, spreads, funding = _monde(100 + graine)
    neuf, ancien = _deux_voies(monkeypatch, R.decomposer_les_pertes, portefeuille, panel, spreads,
                               R.ReplicationConfig(), funding_rates=funding)
    assert neuf == ancien


def test_la_nouvelle_voie_est_bien_empruntee(monkeypatch):
    panel, portefeuille, spreads, funding = _monde(3)
    appels = []
    vrai = panel.at_one
    object.__setattr__(panel, "at_one", lambda t, c: (appels.append(1), vrai(t, c))[1])
    monkeypatch.setattr(R, "INDICES_DE_GRILLE", True)
    R.run_replication(portefeuille, panel, spreads, R.ReplicationConfig(), funding_rates=funding)
    assert appels == []                                          # plus aucun searchsorted par coin et par pas
