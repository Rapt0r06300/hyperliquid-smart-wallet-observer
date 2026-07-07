from hl_observer.copy_wallet.copy_session_controller import start_copy_session, stop_copy_session, update_copy_session


def test_copy_session_start_update_stop_is_local_only():
    state = start_copy_session("s1", watchlist=("0x1",), copy_ratio=0.05)
    assert state.status == "RUNNING"
    assert state.paper_only is True
    assert state.real_execution is False
    state = update_copy_session(state, watchlist=("0x1", "0x2"), copy_ratio=0.02)
    assert len(state.watchlist) == 2
    assert stop_copy_session(state).status == "STOPPED"
