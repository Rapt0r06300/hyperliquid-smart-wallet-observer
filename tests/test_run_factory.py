"""ALPHA FACTORY — pipeline exécutable : ne crashe jamais, sources absentes -> BLOCKED, émet la table."""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import run_factory as RF  # noqa: E402


def test_run_all_sources_absentes_donne_blocked(tmp_path):
    reg = tmp_path / "reg.jsonl"
    out = RF.run_all(data_dir=str(tmp_path), registry_path=str(reg), coins_l2=("BTC",))
    assert out["n_trials"] >= 3
    assert "IDEA | CONFIG FROZEN" in out["table"]
    verdicts = [r["verdict"] for r in out["rows"]]
    assert "BLOCKED_EXTERNAL" in verdicts               # sources absentes -> blocked, pas de crash


def test_run_all_avec_wallet_tape(tmp_path):
    recs = []
    for d in range(4):
        for coin in ("BTC", "ETH", "SOL"):
            recs.append({"adresse": "0xLOSE", "coin": coin, "side": "LONG",
                         "ts_ms": (10 + d) * 86_400_000, "mid_at_fill": 100.0, "mid_forward": 99.9})
    (tmp_path / "leader_fills_forward.jsonl").write_text(
        "\n".join(json.dumps(x) for x in recs), encoding="utf-8")
    out = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r.jsonl"), coins_l2=("BTC",))
    pop = [r for r in out["rows"] if r["idea"].startswith("Wallet population")]
    assert pop and pop[0]["verdict"] in ("KILL", "CANDIDAT")
    # registre relu = mêmes lignes
    assert len(RF.F.TrialRegistry(str(tmp_path / "r.jsonl")).load()) == out["n_trials"]
