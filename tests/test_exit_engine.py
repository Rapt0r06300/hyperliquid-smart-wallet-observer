from hl_observer.exits.exit_engine import build_default_exit_plan


def test_exit_plan_required_before_paper():
    plan = build_default_exit_plan("s1")

    assert plan.hard_stop_bps > 0
    assert plan.leader_reduce_exit
