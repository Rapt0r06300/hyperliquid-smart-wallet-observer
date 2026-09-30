"""[Bloc 6/58] Entrypoint CLI unique : `python -m hl_observer.hyperlab <mode>`.

modes : smoke (chaine complete offline sur fixture -> rapport + verdict), quick/full/deep/maximum.
Sans reseau : tout tourne sur fixtures deterministes. La collecte LIVE reste REQUIRES_NETWORK (hors
smoke). Code de sortie : 0 si la chaine tient, non-zero sinon (utilisable en CI / double-clic Windows)."""
from __future__ import annotations

import json
import os
import sys
import tempfile

from . import data_mesh_catalog as dm
from . import lanes, master

FIXTURE = {
    "session_id": "smoke", "venue": "bybit", "symbole": "BTCUSDT", "ts": 1000.0,
    "records": [
        {"ts": 1720000000000, "venue": "bybit", "symbole": "BTCUSDT", "type": "trade",
         "prix": "60000", "taille": "0.5", "side": "buy"},
        {"ts": 1720000001000, "venue": "bybit", "symbole": "BTCUSDT", "type": "trade",
         "prix": "60010", "taille": "1", "side": "sell"},
    ],
    "copy_action": {"venue": "bybit", "symbole": "BTCUSDT", "side": "buy", "prix_ref": 60000.0},
    "leadlag": ({"bid": 100, "bid_sz": 5, "ask": 101, "ask_sz": 5},
                {"bid": 100, "bid_sz": 9, "ask": 101, "ask_sz": 5}),
    "crossvenue": ({"mid": 60000.0, "venue": "bybit"}, {"mid": 60100.0, "venue": "okx"}),
    "perf_is": [1, 2, 3, 2.5], "perf_oos": [1.1, 1.8, 2.9, 2.4], "sr": 1.2, "n_trials": 20, "T": 250,
    "quotes": [{"bid": 59999.0, "ask": 60001.0}],
    "fills": [{"prix_exec": 60001.0, "mid_ref": 60000.0, "frais": 0.05, "notionnel": 100.0,
               "mid_apres": 60000.5, "side": "buy"}],
    "latences": [10, 20, 30, 40, 50],
    "is_idx": [0, 1], "oos_idx": [2, 3], "forward_idx": [4, 5], "finalistes": ["cfg_a"],
    "blocages": ["collecte live: REQUIRES_NETWORK", "Windows E2E: runner GitHub requis"],
    "prochaine_action": "brancher la collecte live read-only (reseau requis) puis relancer smoke->stable",
}


def _conn(root):
    conn = dm.ouvrir(os.path.join(root, "mesh.db"))
    dm.bootstrap(conn, ts=1000.0)
    return conn


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0] if argv else "smoke"
    root = tempfile.mkdtemp(prefix="hyperlab_")
    conn = _conn(root)
    if mode == "smoke":
        out = lanes.run_session_validee(FIXTURE, root=root, conn=conn)
        print(json.dumps({"mode": "smoke", "verdict_chaine_ok": out["verdict_chaine_ok"],
                          "rapport": out["rapport"]}, indent=2, ensure_ascii=False, default=str))
        return 0 if out["verdict_chaine_ok"] else 1
    if mode in master.MODES:
        out = master.run(mode, root=root, conn=conn, fixtures=FIXTURE)
        print(json.dumps({"mode": mode, "intents": out["intents"], "fills": out["fills"],
                          "rapport": out["rapport"]}, indent=2, ensure_ascii=False, default=str))
        return 0
    sys.stderr.write("mode inconnu: %s (smoke|quick|full|deep|maximum)\n" % mode)
    return 2


if __name__ == "__main__":
    sys.exit(main())
