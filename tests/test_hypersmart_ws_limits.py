from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.realtime_monitor.stream_models import StreamType
from hyper_smart_observer.realtime_monitor.subscriptions import Subscription, SubscriptionPlanner


def test_ws_limit_ten_user_subscriptions():
    subs = [Subscription(StreamType.USER_FILLS, user="0x" + f"{i:040x}") for i in range(11)]

    plan = SubscriptionPlanner(AppConfig(ws_max_user_subscriptions=10)).plan(subs)

    assert len([sub for sub in plan.accepted if sub.user]) == 10
    assert plan.rejected


def test_scanner_ws_shortlist_max_10_users_counts_unique_wallets():
    wallets = ["0x" + f"{i:040x}" for i in range(10)]
    subs = []
    for wallet in wallets:
        subs.append(Subscription(StreamType.USER_FILLS, user=wallet))
        subs.append(Subscription(StreamType.CLEARINGHOUSE_STATE, user=wallet))
    subs.append(Subscription(StreamType.USER_EVENTS, user="0x" + "f" * 40))

    plan = SubscriptionPlanner(AppConfig(ws_max_user_subscriptions=10)).plan(subs)
    accepted_users = {sub.user.lower() for sub in plan.accepted if sub.user}

    assert len(accepted_users) == 10
    assert len(plan.accepted) == 20
    assert len(plan.rejected) == 1
    assert "too many unique user websocket subscriptions" in plan.warnings
