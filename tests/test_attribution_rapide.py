"""``attribute_pnl`` accélérée (24/11/2026) : sorties IDENTIQUES AU BIT à la version d'origine.

Profil réel : 398 s sur 408 s de l'étude de base dans ``attribute_pnl``. La version rapide calcule une fois par coin
ce qui ne dépend que du coin, extrait les indices valides une fois par couple, et n'évalue la rotation qu'aux débuts
de fenêtre de rééquilibrage. Ce test la confronte à la copie figée d'origine sur des données tirées au hasard :
prix manquants et périmés, funding partiel ou absent, demi-spreads absents, instantanés (positions), unités fusionnées.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from _reference_attribution_copiabilite import attribute_pnl_reference  # noqa: E402
from hl_observer.backtesting.copy_vault_copiability_entrees import CopiabilityConfig, PricePanel  # noqa: E402
from hl_observer.backtesting.copy_vault_copiability_mesures import attribute_pnl  # noqa: E402

DEBUT = 1_794_000_000_000


def _monde(graine: int, n_vaults: int = 6):
    rng = np.random.default_rng(graine)
    n = int(rng.integers(300, 900))
    ts = DEBUT + np.cumsum(rng.integers(1_000, 400_000, n)).astype(np.int64)      # plusieurs jours, trous variés
    coins = ("BTC", "ETH", "SOL", "DOGE", "HYPE")
    px = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.002, (n, len(coins))), axis=0))
    px[rng.random((n, len(coins))) < 0.08] = np.nan                                # prix manquants
    px[: int(rng.integers(0, 40)), 3] = np.nan                                     # coin qui démarre tard
    panel = PricePanel(ts=ts, px=px, coins=coins, provenance="TEST", stale_ms=int(rng.integers(60_000, 900_000)))
    lignes = []
    vaults = [f"0x{v:040x}" for v in range(n_vaults)]
    for vault in vaults:
        for coin in rng.choice(coins + ("INCONNU",), size=int(rng.integers(1, 5)), replace=False):
            m = int(rng.integers(1, 40))
            temps = np.sort(rng.integers(ts[0] - 300_000, ts[-1] + 300_000, m))
            pos = 0.0 if rng.random() < 0.5 else float(rng.normal(0, 3))
            for t in temps:
                q = float(rng.normal(0, 2)) or 0.5
                avant, pos = pos, pos + q
                if rng.random() < 0.15:
                    pos = 0.0                                                      # retour à plat
                lignes.append({"vault": vault, "coin": str(coin), "time": int(t),
                               "obs": int(t + rng.integers(0, 600_000)), "start_pos": avant, "after": pos,
                               "signe": 1.0 if pos >= avant else -1.0, "sz": abs(pos - avant) or 0.1,
                               "px": float(100 * np.exp(rng.normal(0, 0.01))),
                               "closed_pnl": float(rng.normal()) if rng.random() < 0.7 else np.nan,
                               "fee": abs(float(rng.normal(0, 0.1))), "crossed": float(rng.random() < 0.6)})
    fills = pd.DataFrame(lignes).sort_values(["vault", "coin", "time"], kind="mergesort").reset_index(drop=True)
    fills["notional"] = fills["px"] * fills["sz"]
    units = {vaults[1]: vaults[0], vaults[4]: vaults[3]}                           # unités fusionnées (sybil)
    spreads = {c: float(rng.uniform(0.5, 8)) for c in coins if rng.random() < 0.7}
    funding = None
    if graine % 3:
        funding = {}
        for c in coins:
            if rng.random() < 0.75:
                taux = rng.normal(0, 1e-5, n)
                taux[rng.random(n) < 0.2] = np.nan                                 # taux inconnu par endroits
                funding[c] = taux
    return fills, panel, spreads, units, funding, rng


def _egaux(a, b, chemin="racine"):
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        assert isinstance(a, np.ndarray) and isinstance(b, np.ndarray), chemin
        assert a.dtype == b.dtype and a.shape == b.shape, chemin
        assert np.array_equal(a, b, equal_nan=True), chemin                       # au bit (NaN compris)
        return
    if isinstance(a, dict):
        assert isinstance(b, dict) and list(a) == list(b), chemin
        for k in a:
            _egaux(a[k], b[k], f"{chemin}.{k}")
        return
    if isinstance(a, (list, tuple)):
        assert type(a) is type(b) and len(a) == len(b), chemin
        for i, (x, y) in enumerate(zip(a, b)):
            _egaux(x, y, f"{chemin}[{i}]")
        return
    if isinstance(a, float) and isinstance(b, float) and np.isnan(a) and np.isnan(b):
        return
    assert type(a) is type(b) and a == b, f"{chemin}: {a!r} != {b!r}"


#: Champs ajoutes le 26/11/2026 avec la regle « funding mesure » : seuls autorises en plus de la reference figee.
NOUVEAUX_CHAMPS_FUNDING = ("funding_measured_k", "funding_coverage_k", "partial_net_excluding_unmeasured_funding_k")


def _egaux_attribution(rapide, origine):
    """Egalite AU BIT avec la reference figee, sous la regle funding du 26/11/2026.

    La reference est la copie d'origine (avant l'acceleration du 24/11). Depuis, ``net_k*_usd`` ne vaut plus le net
    calcule que si le funding est mesure sur au moins ``MIN_FUNDING_COVERAGE`` de l'exposition (sinon ``None``), et
    trois champs funding s'ajoutent. Tout le reste doit rester identique au bit : chaque champ d'origine, le tableau
    journalier, et ``partial_net_excluding_unmeasured_funding`` doit valoir l'ANCIEN net, au bit.
    """
    from hl_observer.backtesting import copy_vault_copiability_mesures as mesures

    seuil = getattr(mesures, "MIN_FUNDING_COVERAGE", None)
    if seuil is None or not isinstance(rapide, dict) or "leaders" not in rapide:
        _egaux(rapide, origine)
        return
    assert [k for k in rapide if k in origine] == list(origine) and set(rapide) == set(origine), "racine"
    for cle in origine:
        if cle not in ("leaders", "daily"):
            _egaux(rapide[cle], origine[cle], cle)
    assert [k for k in rapide["daily"] if k in origine["daily"]] == list(origine["daily"])
    assert all(k.startswith(NOUVEAUX_CHAMPS_FUNDING) for k in rapide["daily"] if k not in origine["daily"])
    for cle in origine["daily"]:
        _egaux(rapide["daily"][cle], origine["daily"][cle], f"daily.{cle}")
    assert len(rapide["leaders"]) == len(origine["leaders"])
    for i, (a, b) in enumerate(zip(rapide["leaders"], origine["leaders"])):
        chemin = f"leaders[{i}]"
        assert all(k in a for k in b), chemin
        assert all(k.startswith(NOUVEAUX_CHAMPS_FUNDING) for k in a if k not in b), chemin
        for cle, valeur in b.items():
            if not (cle.startswith("net_k") and cle.endswith("_usd")):
                _egaux(a[cle], valeur, f"{chemin}.{cle}")
                continue
            k = cle[len("net_k"):-len("_usd")]
            partiel = a[f"partial_net_excluding_unmeasured_funding_k{k}_usd"]
            _egaux(partiel, valeur, f"{chemin}.partial_net_k{k}")              # l'ancien net, au bit
            couverture = a[f"funding_coverage_k{k}"]
            attendu = partiel if couverture is not None and couverture >= seuil else None
            _egaux(a[cle], attendu, f"{chemin}.{cle}")


@pytest.mark.parametrize("graine", range(24))
def test_la_version_rapide_rend_exactement_la_version_d_origine(graine):
    fills, panel, spreads, units, funding, rng = _monde(graine)
    cfg = CopiabilityConfig()
    _egaux_attribution(attribute_pnl(fills, panel, spreads, units, cfg, funding_rates=funding),
           attribute_pnl_reference(fills, panel, spreads, units, cfg, funding_rates=funding))


@pytest.mark.parametrize("graine", range(12))
def test_le_mode_instantanes_rend_exactement_la_version_d_origine(graine):
    """Positions issues d'instantanés : ``ok`` dépend du leader, la position périmée est inconnue."""
    fills, panel, spreads, units, funding, rng = _monde(100 + graine)
    obs = {v: np.sort(rng.integers(panel.ts[0], panel.ts[-1], int(rng.integers(0, 60)))).astype(np.int64)
           for v in fills["vault"].unique() if rng.random() < 0.85}
    cfg = CopiabilityConfig()
    args = dict(observation_times=obs, max_staleness_ms=int(rng.integers(120_000, 3_600_000)),
                measure_execution=bool(graine % 2), funding_rates=funding)
    _egaux_attribution(attribute_pnl(fills, panel, spreads, units, cfg, **args),
           attribute_pnl_reference(fills, panel, spreads, units, cfg, **args))


@pytest.mark.parametrize("instantanes", [False, True])
def test_l_execution_parallele_rend_exactement_la_version_d_origine(instantanes):
    """Plus de 200 couples : les coins partent dans des processus, les sommes se font dans l'ordre d'origine."""
    sys.path.insert(0, str(RACINE / "tools"))
    import etude_copiabilite as E

    fills, panel, spreads, units, funding, rng = _monde(7, n_vaults=160)
    assert fills[fills["coin"] != "INCONNU"].groupby(["vault", "coin"]).ngroups >= 200   # le chemin parallele
    args = {"funding_rates": funding}
    if instantanes:
        args.update(observation_times={v: np.sort(rng.integers(panel.ts[0], panel.ts[-1], 40)).astype(np.int64)
                                       for v in fills["vault"].unique()},
                    max_staleness_ms=1_800_000, measure_execution=False)
    cfg = CopiabilityConfig()
    _egaux_attribution(attribute_pnl(fills, panel, spreads, units, cfg, parallele=E.executeur_parallele(2), **args),
           attribute_pnl_reference(fills, panel, spreads, units, cfg, **args))
