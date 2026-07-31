"""ALPHA FACTORY — pipeline FIX-01 : chaque famille est EXECUTEE (trial reel) ou BLOCKED precis ; jamais de crash."""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import factory_families as FAM  # noqa: E402
from hl_observer.research import run_factory as RF  # noqa: E402


def test_run_all_couvre_TOUTES_les_familles(tmp_path):
    out = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r.jsonl"))
    # une ligne par famille du registre (execution ou BLOCKED), jamais un registre declaratif
    assert out["n_trials"] == out["n_familles"] == len(FAM.FAMILLES)
    assert set(out["familles_couvertes"]) == set(FAM.FAMILLES)
    # data absente -> les familles sortent BLOCKED_EXTERNAL / MORE_DATA, pas ERROR, pas DONE
    verdicts = {r["verdict"] for r in out["rows"]}
    assert "ERROR" not in verdicts
    assert "BLOCKED_EXTERNAL" in verdicts


def test_run_all_execute_reellement_la_population(tmp_path):
    recs = []
    for d in range(4):
        for coin in ("BTC", "ETH", "SOL"):
            recs.append({"adresse": "0xLOSE", "coin": coin, "side": "LONG",
                         "ts_ms": (10 + d) * 86_400_000, "mid_at_fill": 100.0, "mid_forward": 99.9})
    (tmp_path / "leader_fills_forward.jsonl").write_text(
        "\n".join(json.dumps(x) for x in recs), encoding="utf-8")
    out = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r.jsonl"))
    pop = [r for r in out["rows"] if r["_famille"] == "copy_population"][0]
    # la famille a REELLEMENT tourne (trial mesure), pas un BLOCKED
    assert pop["verdict"] in ("KILL", "CANDIDAT") and "IDEA | CONFIG FROZEN" in out["table"]


def test_p13_reset_defaut_est_append_only_avec_dedup(tmp_path):
    reg = str(tmp_path / "r.jsonl")
    out1 = RF.run_all(data_dir=str(tmp_path), registry_path=reg)
    RF.run_all(data_dir=str(tmp_path), registry_path=reg)                 # 2e run IDENTIQUE
    # FIX-03 : append-only sans wipe, 2e run identique DEDUP -> pas de doublons
    assert len(RF.F.TrialRegistry(reg).load()) == out1["n_trials"]
