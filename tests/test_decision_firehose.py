"""Firehose de décisions — chaque décision devient un candidat replay (même flux que le docteur),
même sans ouverture. Mid absent -> pas de candidat fabriqué. Shadow logué à part."""
from __future__ import annotations

from pathlib import Path

from hl_observer.ops.decision_firehose import (
    candidat_depuis_decision, enregistrer_decision, enregistrer_shadow)
from hl_observer.runtime.replay_recorder import read_replay_lines


def test_candidat_direction_et_mid_absent():
    assert candidat_depuis_decision({"coin": "HYPE"}, strategie="carry", ts_s=1.0, mid=None) is None
    c = candidat_depuis_decision({"coin": "hype", "funding_bps_h": 0.125, "gain_net_24h_bps": 47.0,
                                  "viable": True}, strategie="carry", ts_s=1.0, mid=40.0)
    assert c["coin"] == "HYPE" and c["direction"] == "LONG" and c["current_mid"] == 40.0
    assert c["edge_remaining_bps"] == 47.0 and c["accepte"] is True
    neg = candidat_depuis_decision({"coin": "X", "funding_bps_h": -0.2}, strategie="c", ts_s=1.0, mid=5.0)
    assert neg["direction"] == "SHORT"


def test_enregistrer_va_dans_le_flux_replay(tmp_path):
    n = enregistrer_decision(str(tmp_path), {"coin": "HYPE", "funding_bps_h": 0.125,
                                             "gain_net_24h_bps": 47.0, "viable": True},
                             strategie="carry", ts_s=1000.0, mid=40.0)
    assert n == 1
    rows = read_replay_lines(Path(str(tmp_path)) / "runtime" / "replay", "candidates.jsonl")
    assert len(rows) == 1 and rows[0]["coin"] == "HYPE" and rows[0]["strategie"] == "carry"


def test_shadow_logue_ce_qui_serait_ouvert(tmp_path):
    decisions = [{"coin": "BTC", "viable": True, "gain_net_24h_bps": 20.0},
                 {"coin": "ETH", "viable": False}]
    n = enregistrer_shadow(str(tmp_path), "multi_venue", decisions, ts_s=1.0,
                           mids={"BTC": 100.0, "ETH": 50.0})
    assert n == 2                                          # 2 décisions loguées comme candidats shadow
    rows = read_replay_lines(Path(str(tmp_path)) / "runtime" / "replay", "candidates.jsonl")
    assert all(r["shadow"] for r in rows) and len(rows) == 2


# ============ 🔴 MARKS : sans eux le replay ne mesure RIEN (constat 18/07 : 0 mark / 1610 candidats)
def test_marks_ecrits_dans_le_flux_replay(tmp_path):
    from hl_observer.ops.decision_firehose import enregistrer_marks
    n = enregistrer_marks(str(tmp_path), {"HYPE": 40.0, "purr": 0.5, "MAUVAIS": 0.0, "X": None},
                          ts_s=1000.0)
    assert n == 2                                          # seuls les prix VALIDES sont écrits
    rows = read_replay_lines(Path(str(tmp_path)) / "runtime" / "replay", "marks.jsonl")
    coins = {r["coin"] for r in rows}
    assert coins == {"HYPE", "PURR"} and all(r["mid"] > 0 and r["ts"] == 1000.0 for r in rows)


def test_le_runtime_carry_ECRIT_des_marks(tmp_path):
    """Bout-en-bout : un tick du runtime carry doit produire des MARKS (sinon replay mort)."""
    import json, os, time
    os.environ["HYPERSMART_CARRY_HYPE_PAPER"] = "1"
    from hl_observer.funding import carry_paper_runtime as C
    data = Path(str(tmp_path)) / "runtime" / "data"
    data.mkdir(parents=True, exist_ok=True)
    now = int(time.time() * 1000)
    inp = {"ts_ms": now, "coin": "HYPE", "funding_bps_h": 0.125, "base_bps": 0.0,
           "liquidite_spot_usd": 200000.0, "maker": True, "levier_max": 10.0,
           "marge_ratio": 1.0 / 1.5, "pire_hausse_observee": 0.29, "perp_px": 40.0,
           "levier_utilise": 1.5}
    (data / "carry_spot_inputs.json").write_text(json.dumps(inp), encoding="utf-8")
    (data / "carry_spot_shortlist.json").write_text(json.dumps([inp]), encoding="utf-8")
    C.evaluer_et_journaliser(str(tmp_path), now_ms=now)
    marks = read_replay_lines(Path(str(tmp_path)) / "runtime" / "replay", "marks.jsonl")
    assert marks and marks[0]["coin"] == "HYPE" and marks[0]["mid"] == 40.0
