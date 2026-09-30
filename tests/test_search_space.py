"""ALPHA P16 — search space pre-enregistre & hashe : hash stable, cardinalite, freeze, refus hors espace."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import pytest  # noqa: E402

from hl_observer.research import search_space as S  # noqa: E402

_ESP = {"event": ["wallet_open", "ofi_shock"], "state": ["spread_lo"], "filter": ["seuil_q75"],
        "horizon": ["1s", "5s"], "execution": ["TT", "MT"]}


def test_hash_stable_et_cardinalite():
    assert S.hash_espace(_ESP) == S.hash_espace(dict(_ESP))     # deterministe
    assert S.cardinalite(_ESP) == 2 * 1 * 1 * 2 * 2             # produit des tailles


def test_freeze_config_valide_et_hash():
    ss = S.SearchSpace(_ESP)
    g = ss.geler({"event": "ofi_shock", "state": "spread_lo", "filter": "seuil_q75",
                  "horizon": "5s", "execution": "MT"})
    assert ss.verifier_oos(g["config_hash"]) is True
    assert ss.verifier_oos("mauvais_hash") is False            # l'OOS ne mesure QUE la config gelee


def test_refuse_config_hors_espace():
    ss = S.SearchSpace(_ESP)
    with pytest.raises(ValueError):
        ss.geler({"event": "SNOOP", "state": "spread_lo", "filter": "seuil_q75",
                  "horizon": "5s", "execution": "MT"})
