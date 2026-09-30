"""CHANTIER #2 — backfill node_fills_by_block : parse fills, dédup, univers de wallets, couverture de blocs."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import node_fills_backfill as NB   # noqa: E402


class _FakeNode:
    """Client node factice : renvoie des fills synthétiques par bloc (recouvrement volontaire pour tester la dédup)."""

    def __init__(self):
        self.blocs = {
            100: [{"user": "0xA", "coin": "BTC", "side": "B", "px": 100, "sz": 1, "ts_ms": 1, "tid": "t1"},
                  {"user": "0xB", "coin": "ETH", "side": "S", "px": 50, "sz": 2, "ts_ms": 2, "tid": "t2"}],
            101: [{"user": "0xB", "coin": "ETH", "side": "S", "px": 50, "sz": 2, "ts_ms": 2, "tid": "t2"},   # DUP (recouvrement)
                  {"user": "0xC", "coin": "SOL", "side": "B", "px": 10, "sz": 5, "ts_ms": 3, "tid": "t3"}],
            # bloc 102 sauté -> trou
            103: [{"user": "0x%d" % k, "coin": "BTC", "side": "B", "px": 100, "sz": 1, "ts_ms": 10 + k, "tid": "b%d" % k}
                  for k in range(2000)],                                                                      # milliers de wallets
        }

    def fills_by_block(self, block):
        return self.blocs.get(block, [])


def test_chantier2_backfill_dedup_wallets_et_trous(tmp_path):
    out = tmp_path / "fills.jsonl"
    r = NB.backfill(_FakeNode(), [100, 101, 103], str(out))
    assert r["statut"] == "OK"
    assert r["n_wallets"] >= 2000 and r["n_fills"] == 2000 + 3    # t2 dédupliqué (recouvrement), reste conservé
    assert r["trous_blocs"] == [(101, 103)]                       # bloc 102 manquant détecté
    assert out.exists() and r["real_execution"] is False


def test_chantier2_sans_client_est_blocked_external():
    assert NB.backfill(None, [1, 2, 3], "x")["statut"] == "BLOCKED_EXTERNAL"


def test_chantier2_fill_canonique_rejette_incomplet():
    assert NB.fill_canonique({"coin": "BTC"}, block=1) is None   # user manquant -> jamais un fill fabriqué
    fc = NB.fill_canonique({"user": "0xA", "coin": "BTC", "side": "SELL", "px": 1, "sz": 1}, block=7)
    assert fc["side"] == -1.0 and fc["block"] == 7
