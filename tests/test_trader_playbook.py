from hl_observer.analysis.methodology_profiler import build_methodology_profile
from hl_observer.analysis.trader_playbook import generate_trader_playbook


def test_trader_playbook_summarizes_methodology():
    profile = build_methodology_profile(
        wallet_address="0x" + "3" * 40,
        coins=["HYPE", "SOL"],
        opening_types=["MOMENTUM_CHASE_LONG"],
        copyability_score=60,
    )
    playbook = generate_trader_playbook(profile)

    assert "Style estime" in playbook.rule_summary
    assert playbook.status in {"OBSERVE_ONLY", "PAPER_READY"}
