import inspect

import hl_observer.following.paper_follow as paper_follow


def test_paper_follow_never_calls_exchange():
    assert "/exchange" not in inspect.getsource(paper_follow)
