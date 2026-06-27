import json

from hyper_smart_observer.app.main import main
from hyper_smart_observer.copy_mode.candidate_importer import load_leader_candidates_from_file


GOOD = "0x" + "d" * 40


def test_candidate_importer_loads_csv_and_preserves_missing_quality(tmp_path):
    csv_path = tmp_path / "candidates.csv"
    csv_path.write_text(
        "wallet_address,history_days,closed_pnl_points,total_closed_pnl,max_single_trade_pnl,consistency_score\n"
        f"{GOOD},30,40,1000,100,85\n"
        "0xaaaa...bbbb,,,,,\n",
        encoding="utf-8",
    )

    candidates = load_leader_candidates_from_file(csv_path)

    assert len(candidates) == 2
    assert candidates[0].wallet_address == GOOD
    assert candidates[1].wallet_address == "0xaaaa...bbbb"
    assert candidates[1].history_days is None


def test_cli_build_shortlist_file_rejects_truncated_and_writes_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    csv_path = tmp_path / "candidates.csv"
    output_path = tmp_path / "data" / "leaderboard_shortlist.json"
    csv_path.write_text(
        "wallet_address,history_days,closed_pnl_points,total_closed_pnl,max_single_trade_pnl,max_drawdown_pct,consistency_score,per_coin_stability_score,execution_quality_score,sample_confidence,copyability_score\n"
        f"{GOOD},30,40,1000,100,10,90,90,90,90,90\n"
        "0xaaaa...bbbb,30,40,1000,100,10,90,90,90,90,90\n",
        encoding="utf-8",
    )

    code = main(
        [
            "--build-shortlist-file",
            str(csv_path),
            "--shortlist-output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    reasons = [reason for entry in payload["entries"] for reason in entry["refusal_reasons"]]
    assert code == 0
    assert any(entry["status"] == "SHORTLISTED" for entry in payload["entries"])
    assert "TRUNCATED_ADDRESS_REJECTED" in reasons
