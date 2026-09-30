from __future__ import annotations

import json

from hl_observer.research_parallel.plugins import _commun as commun


def test_signal_is_shadow_only_and_preserves_extra() -> None:
    row = commun.signal(12.9, "btc", -1, "v1", edge=3.5)
    assert row == {
        "kind": "SIGNAL_SHADOW",
        "ts_ms": 12,
        "coin": "btc",
        "sens": -1,
        "variante": "v1",
        "real_execution": False,
        "edge": 3.5,
    }


def test_charger_lab_jsonl_missing_invalid_blank_and_limit(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(commun.ISO, "lab_root", lambda root: tmp_path)
    assert commun.charger_lab_jsonl(tmp_path, "missing") == []

    data = tmp_path / "data"
    data.mkdir()
    path = data / "flux.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"n": 1}),
                "not-json",
                "",
                json.dumps({"n": 2}),
                json.dumps({"n": 3}),
            ]
        ),
        encoding="utf-8",
    )
    assert commun.charger_lab_jsonl(tmp_path, "flux", limite=None) == [
        {"n": 1}, {"n": 2}, {"n": 3}
    ]
    assert commun.charger_lab_jsonl(tmp_path, "flux", limite=2) == [{"n": 2}, {"n": 3}]


def test_series_par_coin_filters_invalid_and_sorts() -> None:
    rows = [
        {"coin": "BTC", "value": "2", "ts": 20},
        {"coin": "BTC", "value": "1", "ts": 10},
        {"coin": "ETH", "value": None, "ts": 1},
        {"coin": None, "value": 1, "ts": 1},
        {"coin": "SOL", "value": "bad", "ts": 2},
        {"coin": "HYPE", "value": 4, "ts": None},
    ]
    assert commun.series_par_coin(rows, "value", ts_champ="ts") == {
        "BTC": [(10.0, 1.0), (20.0, 2.0)],
        "SOL": [],
    }


def test_prix_bbo_hl_missing_and_filters(monkeypatch, tmp_path) -> None:
    assert commun.prix_bbo_hl(tmp_path, ["BTC", "ETH"]) == {"BTC": [], "ETH": []}

    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    tape = data / "bbo_tape.jsonl"
    rows = [
        "not-json",
        json.dumps({"venue": "DYDX", "coin": "BTC", "ts_wall_ms": 1, "bid": 1, "ask": 2}),
        json.dumps({"venue": "HL", "coin": "SOL", "ts_wall_ms": 1, "bid": 1, "ask": 2}),
        json.dumps({"venue": "HL", "coin": "BTC", "ts_wall_ms": 1000, "bid": 0, "ask": 2}),
        json.dumps({"venue": "HL", "coin": "BTC", "ts_wall_ms": 1000, "bid": 2, "ask": 2}),
        json.dumps({"venue": "HL", "coin": "BTC", "ts_wall_ms": 1000, "bid": 1, "ask": 2}),
        json.dumps({"venue": "HL", "coin": "BTC", "ts_wall_ms": 1500, "bid": 1.1, "ask": 2.1}),
        json.dumps({"venue": "HL", "coin": "BTC", "ts_wall_ms": 6000, "bid": 1.2, "ask": 2.2}),
        json.dumps({"venue": "HL", "coin": "ETH", "ts_wall_ms": 7000, "bid": 3, "ask": 4}),
    ]
    tape.write_text("\n".join(rows), encoding="utf-8")
    out = commun.prix_bbo_hl(tmp_path, ["BTC", "ETH"], ds_ms=5000, limite_lignes=100)
    assert out == {
        "BTC": [(1000.0, 1.0, 2.0), (6000.0, 1.2, 2.2)],
        "ETH": [(7000.0, 3.0, 4.0)],
    }
    limited = commun.prix_bbo_hl(tmp_path, ["BTC"], ds_ms=1, limite_lignes=2)
    assert limited == {"BTC": []}


def test_regime_and_authorization(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(commun.ISO, "lab_root", lambda root: tmp_path)
    assert commun.regime_courant(tmp_path) == {"autorises": None}
    data = tmp_path / "data"
    data.mkdir()
    path = data / "regime.json"
    path.write_text("{", encoding="utf-8")
    assert commun.regime_courant(tmp_path) == {"autorises": None}
    path.write_text(json.dumps({"autorises": ["P1"]}), encoding="utf-8")
    regime = commun.regime_courant(tmp_path)
    assert commun.autorise(regime, "P1") is True
    assert commun.autorise(regime, "P2") is False
    assert commun.autorise({"autorises": None}, "anything") is True
