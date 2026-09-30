"""LOT12 — NATIVE_ALPHA_V1 : détecteurs + mesure prouvés sans réseau (Flo 26/07)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("na", _ROOT / "tools" / "native_alpha_v1.py")
NA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(NA)


def test_huit_variantes_figees():
    assert len(NA.VARIANTES) == 8 and len(set(NA.VARIANTES)) == 8


def test_serie_avec_tailles_tolere_v1_et_v2():
    # v1 [px,sz] et v2 [px,sz,n] coexistent (migration additive)
    l2 = [{"coin": "BTC", "ts_wall_ms": 0, "bids": [[100.0, 3.0]], "asks": [[100.1, 4.0]]},          # v1
          {"coin": "BTC", "ts_wall_ms": 1000, "bids": [[100.0, 3.0, 7]], "asks": [[100.1, 4.0, 2]]}]  # v2
    s = NA._serie_avec_tailles(l2)
    assert s["BTC"][0][5] == 0 and s["BTC"][1][5] == 7, "n absent -> 0 (v1) ; n present (v2)"


def test_continuation_et_reversal_sont_opposes():
    l2 = [{"coin": "X", "ts_wall_ms": 0, "bids": [[100, 10], [99.9, 10], [99.8, 10], [99.7, 10], [99.6, 10]],
           "asks": [[100.1, 10], [100.2, 10], [100.3, 10], [100.4, 10], [100.5, 10]]},
          {"coin": "X", "ts_wall_ms": 1000, "bids": [[100, 40], [99.9, 40], [99.8, 40], [99.7, 40], [99.6, 40]],
           "asks": [[100.1, 5], [100.2, 5], [100.3, 5], [100.4, 5], [100.5, 5]]}]
    data = {"l2": l2, "serie": NA.MEC._serie_bbo(l2)}
    cont = NA.detecter("MLOFI_CONTINUATION", data)
    rev = NA.detecter("MLOFI_REVERSAL", data)
    assert cont and rev and cont[0]["sens"] == -rev[0]["sens"], "reversal = miroir de continuation"


def test_mesurer_deny_by_default_sur_data_absente():
    data = {"l2": [], "trades": [], "ctx": [], "serie": {}, "serie_sz": {}, "root": Path(".")}
    r = NA.mesurer("MLOFI_CONTINUATION", data)
    assert r["decision"] == "SHADOW" and r["motif"] == "INSUFFISANT" and r["n_episodes_indep"] == 0


def test_markouts_horizons_100ms_a_60min():
    assert 0.1 in NA.HORIZONS_S and 0.25 in NA.HORIZONS_S and 3600 in NA.HORIZONS_S    # sub-seconde -> 60 min
