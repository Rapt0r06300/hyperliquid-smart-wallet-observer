"""Promotion des candidats observés (rectif Flo 23/07) : score fréquence/copyabilité/shadow depuis le
journal de fills, promotion des 2 meilleurs en mini-PROBE (5-10 $) SI shadow net>0. Aucun réseau."""
from __future__ import annotations

import json

from hl_observer.experimental import promotion_candidats as PC


def _journal(root, lignes):
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "data" / "fills_journal.jsonl").write_text("\n".join(json.dumps(x) for x in lignes))


def test_scorer_et_promouvoir(tmp_path):
    T = 1_000_000_000_000
    # WIN : 6 OPEN sur DOT (coin PROBE), tape montante -> shadow>0. FLAT : 6 OPEN mais tape plate -> shadow 0.
    lignes = []
    for i in range(6):
        lignes.append({"vault": "0xWIN", "coin": "DOT", "dir": "Open Long", "fill_ts_ms": T + i * 60000})
        lignes.append({"vault": "0xFLAT", "coin": "DOT", "dir": "Open Long", "fill_ts_ms": T + i * 60000})
    _journal(tmp_path, lignes)
    tape = {"DOT": [(T + i * 60000, 100.0 + i * 0.1) for i in range(200)]}   # +~10 bps/min -> shadow>0
    scores = PC.scorer_candidats(tmp_path, coins_probe={"DOT"}, tape=tape,
                                 candidats_observes={"0xWIN", "0xFLAT"})
    assert len(scores) == 2 and all(s["copyabilite"] == 1.0 for s in scores)   # tous OPEN sur DOT (PROBE)
    promus = PC.promouvoir(scores)
    assert "0xWIN" in promus and promus["0xWIN"]["notional_usd"] == PC.NOTIONAL_MINI_USD   # promu en mini
    assert 5.0 <= promus["0xWIN"]["notional_usd"] <= 10.0


def test_pas_de_promotion_sans_shadow_positif(tmp_path):
    T = 1_000_000_000_000
    _journal(tmp_path, [{"vault": "0xV", "coin": "DOT", "dir": "Open Long", "fill_ts_ms": T + i * 60000} for i in range(6)])
    tape = {"DOT": [(T + i * 60000, 100.0) for i in range(200)]}             # plat -> shadow ~0 -> pas promu
    scores = PC.scorer_candidats(tmp_path, coins_probe={"DOT"}, tape=tape, candidats_observes={"0xV"})
    assert PC.promouvoir(scores) == {}                                       # deny-by-default


def test_construire_ecrit_et_relit(tmp_path):
    T = 1_000_000_000_000
    _journal(tmp_path, [{"vault": "0xW", "coin": "DOT", "dir": "Open Long", "fill_ts_ms": T + i * 60000} for i in range(6)])
    tape = {"DOT": [(T + i * 60000, 100.0 + i * 0.1) for i in range(200)]}
    PC.construire(tmp_path, coins_probe={"DOT"}, tape=tape, candidats_observes={"0xW"})
    assert "0xW" in PC.charger_promus(tmp_path)
