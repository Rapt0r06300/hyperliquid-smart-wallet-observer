from tools.build_closure_report import (
    global_closure_evidence_receipt, scoreboard_evidence_receipt,
    terminal_campaign_receipt, unique_trade_count_receipt,
)


def test_asf_017_terminal_campaign():
    assert terminal_campaign_receipt(campaign_id="c1", status="COMPLETE", phase="ANALYZE", epoch=1)["status"] == "PROVEN"


def test_asf_018_unique_trade_count():
    assert unique_trade_count_receipt(trade_ids=["t1", "t1", "t2"], unique_trade_ids=["t1", "t2"], declared_total=2)["status"] == "PROVEN"


def test_asf_019_global_closure_evidence():
    assert global_closure_evidence_receipt(required_sections=("scope",), observed_sections=("scope",), evidence_digest="a" * 64)["status"] == "PROVEN"


def test_asf_020_scoreboard_evidence():
    assert scoreboard_evidence_receipt(scoreboard_sha="a" * 64, campaign_id="c1", phase_epoch=1, source_collection_epoch=1)["status"] == "PROVEN"
