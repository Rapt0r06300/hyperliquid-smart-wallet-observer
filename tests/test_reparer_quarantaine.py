"""Réparation de la quarantaine (23/11/2026) : ne casser rien, ne jeter aucune donnée viable, ne rien doubler.

Verrouille :
- une ligne écartée par une ANCIENNE règle, acceptée aujourd'hui et absente du coffre, entre UNE fois (même si
  deux lots l'ont mise en quarantaine), marquée ``repare_depuis_quarantaine`` ;
- une ligne déjà au coffre n'est jamais redéposée ; une ligne encore refusée reste en quarantaine ;
- une réception antérieure à la bourse (au-delà de 5 s) n'est jamais « réparée » ;
- ``--plan`` n'écrit rien ; les fichiers de quarantaine ne sont jamais modifiés.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import reparer_quarantaine as RQ  # noqa: E402

NOW = 1_795_000_000_000


def _trade(tid: int, ex: int, recu: int | None = None) -> dict:
    return {"schema_version": "hypersmart.copy_vault_trades.v1", "coin": "ZEC", "exchange_ts_ms": ex,
            "received_at_ms": ex + 108 if recu is None else recu, "price": 954.39, "size": 0.02,
            "aggressor_side": "BUY", "hash": f"0x{tid:04x}", "tid": tid, "source": "HYPERLIQUID_TRADES_WS"}


def _quarantaine(root: Path, lot: str, lignes: list[dict]) -> Path:
    f = root / RQ.QUARANTAINE / lot / "trades_marche__copy_vault_trades_lane.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(x) + "\n" for x in lignes), encoding="utf-8")
    return f


def _coffre(root: Path, lignes: list[dict]) -> None:
    rel = "runtime/coffre_certifie/local/shards/trades_marche/lot__copy_vault_trades_lane.jsonl.gz"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as g:
        g.writelines(json.dumps(x) + "\n" for x in lignes)
    (root / RQ.INDEX).write_text(json.dumps({"shards": [{
        "famille": "trades_marche", "shard": rel, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "deposes": len(lignes), "ts_min_ms": NOW - 3_600_000, "ts_max_ms": NOW, "coins": ["ZEC"]}]}), encoding="utf-8")


def _deposes(root: Path) -> list[dict]:
    idx = json.loads((root / RQ.INDEX).read_text(encoding="utf-8"))
    out = []
    for s in idx["shards"]:
        with gzip.open(root / s["shard"], "rt", encoding="utf-8") as g:
            out += [json.loads(x) for x in g]
    return out


def test_repare_une_fois_ce_qui_manque_et_ne_touche_ni_au_coffre_ni_a_la_quarantaine(tmp_path):
    deja = _trade(1, NOW - 60_000)
    manque = _trade(2, NOW - 50_000)
    refuse = {**_trade(3, NOW - 40_000), "price": -1}
    triche = _trade(4, NOW - 30_000, recu=NOW - 90_000)                       # reçu 60 s AVANT la bourse
    q1 = _quarantaine(tmp_path, "20261113T000000Z_a", [{"raison": "timestamp_futur", "record": r}
                                                        for r in (deja, manque, refuse, triche)])
    q2 = _quarantaine(tmp_path, "20261114T000000Z_b", [{"raison": "timestamp_futur", "record": manque}])
    avant = (q1.read_bytes(), q2.read_bytes())
    _coffre(tmp_path, [{**deja, "tier": "LOCAL"}])

    assert RQ.main(["--racine", str(tmp_path), "--plan", "--now-ms", str(NOW)]) == 0
    assert not list((tmp_path / RQ.HISTOIRE).glob("*.jsonl.gz")) and len(_deposes(tmp_path)) == 1   # plan : rien
    assert RQ.main(["--racine", str(tmp_path), "--now-ms", str(NOW)]) == 0
    deposes = _deposes(tmp_path)
    repares = [x for x in deposes if x.get("repare_depuis_quarantaine")]
    assert [x["tid"] for x in repares] == [2]                                  # une seule fois, malgré deux lots
    rubans = list((tmp_path / RQ.HISTOIRE).glob("*.jsonl.gz"))
    assert len(rubans) == 1 and sum(1 for _ in gzip.open(rubans[0], "rt", encoding="utf-8")) == 1  # pas même en transit
    assert repares[0]["repare_depuis_quarantaine"]["raison_initiale"] == "timestamp_futur"
    assert sorted(x["tid"] for x in deposes) == [1, 2]                        # le déjà-là n'est pas doublé
    assert (q1.read_bytes(), q2.read_bytes()) == avant                         # quarantaine intacte
    bilan = json.loads((tmp_path / RQ.RAPPORT).read_text(encoding="utf-8"))["passages"][-1]["bilan"]
    assert bilan["reception_avant_la_bourse"] == 1 and bilan["toujours_refusee:px_invalide"] == 1
    assert bilan["deja_au_coffre:trades_marche"] == 1 and bilan["doublon_dans_la_quarantaine"] == 1


def test_un_second_passage_ne_repare_plus_rien(tmp_path):
    _quarantaine(tmp_path, "20261113T000000Z_a", [{"raison": "timestamp_futur", "record": _trade(2, NOW - 50_000)}])
    _coffre(tmp_path, [])
    assert RQ.main(["--racine", str(tmp_path), "--now-ms", str(NOW)]) == 0
    assert RQ.main(["--racine", str(tmp_path), "--now-ms", str(NOW)]) == 0
    assert [x["tid"] for x in _deposes(tmp_path)] == [2]
